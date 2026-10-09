"""Local GGUF backend: llama-cpp-python with a multimodal chat_handler.

The model discovery, mmproj resolution, multimodal chat_handler builder and
the pinned/LRU ModelCache follow the approach of the user's
ComfyUI_qwen_chat_models nodes (`alex_qwen_VL_model` / `alex_qwen_chat_model`):
recursive scan of ComfyUI `models/LLM` (and `llm`) via folder_paths, `_GGUF__`
prefixed dropdown entries, `auto`/`none` mmproj resolution preferring the
projector that sits next to the selected model, and one shared cache so
several nodes in one workflow never reload the same model.

`LocalLLMClient.chat(payload)` is a drop-in replacement for the remote
OpenAI-compatible client: it accepts the same OpenAI-style messages
(system + user with image_url / input_audio parts) and returns the same
OpenAI-style response dict, so every business node works unchanged on both
backends.
"""

import gc
import inspect
import math
import os
import threading
import time

# ggml's CUDA VMM pool allocator (ggml_cuda_pool_vmm::alloc) has been observed
# to abort the whole process on some newer driver/CUDA combinations even with
# free VRAM. Fall back to the classic allocator unless the user overrides.
os.environ.setdefault("GGML_CUDA_NO_VMM", "1")

try:
    import folder_paths
except ImportError:  # standalone diagnose.py / smoke tests
    folder_paths = None

try:
    from llama_cpp import Llama as LlamaGGUF
    _HAS_LLAMA_CPP = True
    _LLAMA_CPP_IMPORT_ERROR = ""
except Exception as _llama_exc:  # ImportError, or OSError from a wheel
    # built against a different CUDA/libstdc++ (undefined symbol). A broken
    # llama_cpp must never break plugin import; local nodes then report the
    # original error at run time.
    _HAS_LLAMA_CPP = False
    _LLAMA_CPP_IMPORT_ERROR = f"{type(_llama_exc).__name__}: {_llama_exc}"
    print(f"[AlexMiniMax-Local] llama_cpp import failed: {_LLAMA_CPP_IMPORT_ERROR}")

try:
    import comfy.model_management as comfy_mm
except ImportError:  # pragma: no cover
    comfy_mm = None


# ------------------------------------------------------------
# GGUF / mmproj discovery (folder_paths only, never absolute paths)
# ------------------------------------------------------------

_GGUF_PATH_MAP = {}


def _get_llm_dirs():
    if folder_paths is None:
        return []
    base = folder_paths.models_dir
    dirs = []
    for subdir in ("LLM", "llm"):
        p = os.path.join(base, subdir)
        if os.path.isdir(p):
            dirs.append(p)
    return list(dict.fromkeys(dirs))


def _collect_from_dir(llm_dir, want_mmproj):
    results = []
    for root, _dirs, files in os.walk(llm_dir):
        for entry in files:
            lower = entry.lower()
            if not lower.endswith(".gguf"):
                continue
            is_mmproj = "mmproj" in lower
            if is_mmproj != want_mmproj:
                continue
            full_path = os.path.join(root, entry)
            results.append((os.path.relpath(full_path, llm_dir), full_path))
    results.sort(key=lambda item: item[0])
    return results


def collect_gguf_files():
    results = []
    for llm_dir in _get_llm_dirs():
        results.extend(_collect_from_dir(llm_dir, want_mmproj=False))
    results.sort(key=lambda item: item[0])
    _GGUF_PATH_MAP.clear()
    for display_name, full_path in results:
        _GGUF_PATH_MAP[f"_GGUF__{display_name}"] = full_path
    return results


def collect_mmproj_files():
    results = []
    for llm_dir in _get_llm_dirs():
        results.extend(_collect_from_dir(llm_dir, want_mmproj=True))
    results.sort(key=lambda item: item[0])
    return results


def local_model_options():
    """Dropdown options for the local GGUF main model."""
    entries = collect_gguf_files()
    return [f"_GGUF__{name}" for name, _ in entries] or ["(未找到GGUF模型，请放入 ComfyUI/models/LLM/)"]


def local_mmproj_options():
    entries = collect_mmproj_files()
    return ["auto", "none"] + [f"_MMPOJ__{name}" for name, _ in entries]


def resolve_mmproj_path(mmproj, model):
    """Resolve the vision projector path (alex_qwen_VL_model semantics)."""
    if mmproj == "none" or not mmproj:
        return ""
    if mmproj == "auto":
        if model in _GGUF_PATH_MAP:
            model_dir = os.path.dirname(_GGUF_PATH_MAP[model])
            for root, _dirs, files in os.walk(model_dir):
                for entry in files:
                    if entry.lower().endswith(".gguf") and "mmproj" in entry.lower():
                        return os.path.join(root, entry)
        all_mmproj = collect_mmproj_files()
        return all_mmproj[0][1] if all_mmproj else ""
    if mmproj.startswith("_MMPOJ__"):
        rel = mmproj[len("_MMPOJ__"):]
        for name, full in collect_mmproj_files():
            if name == rel:
                return full
    return ""


def resolve_gguf_path(model):
    if model in _GGUF_PATH_MAP:
        return _GGUF_PATH_MAP[model]
    return ""


# ------------------------------------------------------------
# Multimodal chat_handler builder (the KEY fix for Qwen-VL GGUF vision)
# ------------------------------------------------------------

def build_vision_chat_handler(mmproj_path):
    """Return (handler_cls, handler_kwargs) or (None, None) for text-only."""
    if not mmproj_path or not os.path.isfile(mmproj_path):
        return None, None
    try:
        import llama_cpp.llama_chat_format as chat_format_module
    except Exception as exc:  # pragma: no cover
        print(f"[AlexMiniMax-Local] cannot import llama_chat_format: {exc}")
        return None, None

    handler_cls = None
    for name in ("Qwen3VLChatHandler", "Qwen25VLChatHandler", "Qwen2VLChatHandler",
                 "Llava15ChatHandler", "LlavaChatHandler"):
        handler_cls = getattr(chat_format_module, name, None)
        if handler_cls is not None:
            break
    if handler_cls is None:
        print("[AlexMiniMax-Local] no multimodal handler in this llama_cpp build; "
              "image/video inputs will be ignored.")
        return None, None

    handler_kwargs = {
        "clip_model_path": mmproj_path,
        "image_max_tokens": 4096,
        "force_reasoning": False,
        "verbose": False,
    }
    try:
        accepted = set(inspect.signature(handler_cls.__init__).parameters)
        handler_kwargs = {key: value for key, value in handler_kwargs.items() if key in accepted}
    except Exception:
        pass
    return handler_cls, handler_kwargs


# ------------------------------------------------------------
# Model cache (pinned + LRU), shared by every *_local node
# ------------------------------------------------------------

class ModelCache:
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()
        self.max_loaded_models = int(os.environ.get("ALEX_MAX_LOADED_MODELS", "2"))

    @staticmethod
    def _make_key(checkpoint, quantization, family):
        return f"{checkpoint}|{quantization}|{family}"

    def get(self, checkpoint, quantization, family, loader_func, *, pinned=False):
        key = self._make_key(checkpoint, quantization, family)
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                entry["last_used"] = time.time()
                return entry["resources"]
            resources = loader_func()
            self._cache[key] = {
                "resources": resources,
                "family": family,
                "pinned": bool(pinned),
                "last_used": time.time(),
            }
            self._evict_if_needed()
            return resources

    def release(self, checkpoint, quantization, family, *, offload_after_used=False):
        if not offload_after_used:
            return
        with self._lock:
            self._unload_key(self._make_key(checkpoint, quantization, family))

    def has(self, checkpoint, quantization, family) -> bool:
        with self._lock:
            return self._make_key(checkpoint, quantization, family) in self._cache

    def _evict_if_needed(self):
        while len(self._cache) > self.max_loaded_models:
            candidates = [(key, value) for key, value in self._cache.items() if not value["pinned"]]
            if not candidates:
                break
            candidates.sort(key=lambda item: item[1]["last_used"])
            self._unload_key(candidates[0][0])

    def _unload_key(self, key):
        entry = self._cache.pop(key, None)
        if not entry:
            return
        for obj in list(entry["resources"].values()):
            # Drop the vision tower reference early: the chat handler owns the
            # mmproj/clip model, and llama.cpp's close() does not free it.
            for attr in ("_chat_handler", "chat_handler"):
                try:
                    if getattr(obj, attr, None) is not None:
                        setattr(obj, attr, None)
                except Exception:
                    pass
            close = getattr(obj, "close", None)
            freed = False
            if callable(close):
                try:
                    close()
                    freed = True
                except Exception:
                    pass
            if not freed:
                # Older llama-cpp-python builds without Llama.close():
                # free context and model manually.
                for attr in ("_ctx", "_model"):
                    handle = getattr(obj, attr, None)
                    if handle is None:
                        continue
                    try:
                        handle.free()
                    except Exception:
                        pass
        entry["resources"].clear()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        if comfy_mm:
            try:
                soft_empty = getattr(comfy_mm, "soft_empty_cache", None)
                if callable(soft_empty):
                    soft_empty(force=True) if "force" in inspect.signature(soft_empty).parameters else soft_empty()
            except Exception:
                pass


model_cache = ModelCache()


# ------------------------------------------------------------
# The local client
# ------------------------------------------------------------

def _payload_image_count(messages):
    count = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        count += sum(1 for item in content if isinstance(item, dict) and item.get("type") == "image_url")
    return count


def _data_uri_size(url):
    try:
        import base64
        import io

        from PIL import Image
        if isinstance(url, str) and url.startswith("data:") and "," in url:
            raw = base64.b64decode(url.split(",", 1)[1])
            with Image.open(io.BytesIO(raw)) as image:
                return image.size
    except Exception:
        return None
    return None


def estimate_vision_tokens(messages, image_min, image_max, qwen_style=True):
    """Estimate real vision-token cost instead of worst-case image_max_tokens.

    Qwen-VL handlers encode an image as ceil(w/28)*ceil(h/28) merged patches
    (verified against llama.cpp `image_tokens->nx/ny` logs), so a 392x588
    image costs ~294 tokens, not 4096. Other handlers keep
    the conservative image_max_tokens behaviour.
    """
    total = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for item in content:
            if not (isinstance(item, dict) and item.get("type") == "image_url"):
                continue
            size = _data_uri_size((item.get("image_url") or {}).get("url", ""))
            if qwen_style and size:
                width, height = size
                estimated = math.ceil(width / 28.0) * math.ceil(height / 28.0)
                estimated = min(max(estimated, int(image_min)), int(image_max))
            else:
                estimated = int(image_max)
            total += estimated
    return total


def _gguf_meta(path):
    """Read block_count / KV geometry from GGUF metadata (best effort)."""
    meta = {"layers": None, "kv_bytes_per_token": None}
    try:
        from llama_cpp.gguf_reader import GGUFReader
        reader = GGUFReader(path, mode="rb")
        architecture = reader.fields.get("general.architecture")
        architecture = str(architecture.parts[0]) if architecture is not None else ""

        def meta_int(key):
            field = reader.fields.get(f"{architecture}.{key}")
            if field is None:
                return None
            try:
                return int(field.parts[0])
            except Exception:
                return None

        layers = meta_int("block_count")
        kv_heads = meta_int("attention.head_count_kv")
        head_dim = meta_int("attention.head_length")
        embedding = meta_int("embedding_length")
        if not head_dim and embedding and kv_heads:
            head_dim = embedding // kv_heads
        meta["layers"] = layers
        if layers and kv_heads and head_dim:
            # K + V, f16 KV cache (llama.cpp default)
            meta["kv_bytes_per_token"] = 2 * layers * kv_heads * head_dim * 2
    except Exception:
        pass
    return meta


def _preflight_vram_check(gguf_path, mmproj_path, n_ctx, n_gpu_layers):
    """Intercept certain OOM before llama.cpp abort()s the whole process.

    llama.cpp CUDA allocation failure calls ggml_abort() -> the entire
    ComfyUI process dies (core dumped); Python cannot catch it. This check
    raises a normal ValueError with concrete remedies instead.
    """
    if os.environ.get("ALEX_SKIP_VRAM_CHECK") == "1":
        return
    try:
        import torch
        if not torch.cuda.is_available():
            return
        free_bytes, _total_bytes = torch.cuda.mem_get_info()
    except Exception:
        return

    gib = 1024 ** 3
    model_bytes = os.path.getsize(gguf_path)
    mmproj_bytes = os.path.getsize(mmproj_path) if mmproj_path and os.path.isfile(mmproj_path) else 0
    meta = _gguf_meta(gguf_path)
    kv_per_token = meta["kv_bytes_per_token"] or int(0.14 * 1024 * 1024)  # ~0.14 MB/token fallback
    layers = meta["layers"] or 0

    if n_gpu_layers >= 0 and layers:
        gpu_fraction = min(1.0, n_gpu_layers / float(layers))
    else:
        gpu_fraction = 1.0
    required = (model_bytes + mmproj_bytes) * gpu_fraction + kv_per_token * n_ctx * gpu_fraction + 1.2 * gib

    if required > free_bytes * 0.92:
        raise ValueError(
            "显存预检失败（llama.cpp 显存不足会直接 abort 整个 ComfyUI 进程，这里提前拦截）：\n"
            f"  预计需要 ≈ {required / gib:.1f} GB"
            f"（模型 {model_bytes / gib:.1f} + 视觉投影 {mmproj_bytes / gib:.1f}"
            f" + KV缓存 {kv_per_token * n_ctx / gib:.1f} + 计算缓冲 ~1.2，GPU层占比 {gpu_fraction:.0%}）\n"
            f"  当前 CUDA 空闲 ≈ {free_bytes / gib:.1f} GB（n_ctx={n_ctx}）\n"
            "建议：① 降低「📐本地上下文长度」或「🔢图像最大token」；"
            "② 把「🎮GPU层数」改为部分层数（如 20）；③ 先卸载 ComfyUI 中占显存的生图/视频模型；"
            "④ 确认显存确实足够时，可设环境变量 ALEX_SKIP_VRAM_CHECK=1 跳过本检查。"
        )


class LocalLLMClient:
    """OpenAI-compatible facade over a cached llama.cpp model."""

    def __init__(self, settings):
        if not _HAS_LLAMA_CPP:
            if _LLAMA_CPP_IMPORT_ERROR:
                raise RuntimeError(
                    "本地GGUF推理需要可导入的 'llama-cpp-python'，但当前导入失败："
                    f"{_LLAMA_CPP_IMPORT_ERROR}\n"
                    "常见原因：已安装的 wheel 与本机 CUDA/驱动/libstdc++ 不匹配（undefined symbol）。"
                    "请换用与 CUDA 版本匹配的构建（参考 JamePeng/llama-cpp-python Releases），"
                    "或先 pip install llama-cpp-python 源码构建。"
                )
            raise RuntimeError("本地GGUF推理需要 'llama-cpp-python'。请执行: pip install llama-cpp-python")
        self.settings = dict(settings)
        self._loaded_cache_key = None

    def _ensure_model(self, payload):
        settings = self.settings
        max_tokens = int(payload.get("max_tokens", 1024))
        image_count = _payload_image_count(payload.get("messages", []))
        n_ctx = int(settings["n_ctx"])

        gguf_path = resolve_gguf_path(settings["model_file"])
        if not gguf_path or not os.path.isfile(gguf_path):
            raise FileNotFoundError(
                f"未找到GGUF模型文件：{settings['model_file']}。请将模型放入 ComfyUI/models/LLM/ 目录。"
            )
        mmproj_path = resolve_mmproj_path(settings["mmproj_file"], settings["model_file"])
        if image_count and not mmproj_path:
            raise ValueError("请求包含图片/视频帧，但该节点没有解析到mmproj视觉投影，请选择匹配的mmproj。")

        if image_count:
            handler_cls, _probe_kwargs = build_vision_chat_handler(mmproj_path)
            vision_tokens = estimate_vision_tokens(
                payload.get("messages", []),
                int(settings.get("image_min_tokens", 1024)),
                int(settings.get("image_max_tokens", 4096)),
                qwen_style=handler_cls is not None and "Qwen" in handler_cls.__name__,
            )
            required = vision_tokens + max_tokens + 512
            if required > 131072:
                raise ValueError(
                    "当前图片数量、图像最大token与输出token需要超过131072上下文。"
                    "请减少图片数量、图像最大token或最大输出令牌。"
                )
            n_ctx = max(n_ctx, required)

        n_gpu_layers = int(settings.get("n_gpu_layers", -1))
        cache_key = f"{gguf_path}|ctx{n_ctx}|mmproj{mmproj_path}"
        # A cache hit allocates nothing new, so the VRAM pre-check must be
        # skipped for it; otherwise the resident model itself would be
        # counted as a deficit and the second run would always fail.
        if not model_cache.has(cache_key, "gguf", "alex_minimax_model"):
            _preflight_vram_check(gguf_path, mmproj_path, n_ctx, n_gpu_layers)

        def load_model():
            llm_kwargs = {
                "model_path": gguf_path,
                "n_gpu_layers": n_gpu_layers,
                "n_ctx": n_ctx,
                "flash_attn": False,
                "verbose": False,
            }
            handler_cls, handler_kwargs = build_vision_chat_handler(mmproj_path)
            if handler_cls is not None:
                llm_kwargs["chat_handler"] = handler_cls(**handler_kwargs)
                llm_kwargs["image_min_tokens"] = int(settings.get("image_min_tokens", 1024))
                llm_kwargs["image_max_tokens"] = int(settings.get("image_max_tokens", 4096))
                print(f"[AlexMiniMax-Local] multimodal handler {handler_cls.__name__} "
                      f"for {image_count} image(s)")
            else:
                llm_kwargs["chat_format"] = "chatml"
                if image_count:
                    raise ValueError("当前llama_cpp构建没有可用的多模态chat_handler，无法分析图片。")
            print(f"[AlexMiniMax-Local] LOADING MODEL: {gguf_path} (n_ctx={n_ctx})")
            return {"model": LlamaGGUF(**llm_kwargs)}

        resources = model_cache.get(
            cache_key, "gguf", "alex_minimax_model", load_model,
            pinned=bool(settings.get("model_loaded_permanently", False)),
        )
        # Remember the EXACT cache key: rebuilding it at release time from
        # llm.n_ctx / re-resolved paths can drift across llama-cpp
        # versions, which made offload silently unload nothing.
        self._loaded_cache_key = cache_key
        return resources["model"]

    def chat(self, payload):
        llm = self._ensure_model(payload)
        try:
            return llm.create_chat_completion(
                messages=payload.get("messages", []),
                temperature=float(payload.get("temperature", 0.4)),
                max_tokens=int(payload.get("max_tokens", 1024)),
                top_p=float(payload.get("top_p", 1.0)),
                top_k=int(self.settings.get("top_k", 20)),
                min_p=float(self.settings.get("min_p", 0.05)),
                repeat_penalty=float(self.settings.get("repeat_penalty", 1.1)),
                seed=int(payload.get("seed", 0)) if payload.get("seed") is not None else None,
            )
        finally:
            try:
                llm.n_tokens = 0
                llm._ctx.memory_clear(True)
                if getattr(llm, "is_hybrid", False) and llm._hybrid_cache_mgr is not None:
                    llm._hybrid_cache_mgr.clear()
            except Exception:
                pass
            if bool(self.settings.get("offload_after_used", False)):
                print("[AlexMiniMax-Local] 🧹 推理后卸载模型：释放缓存与显存…")
            model_cache.release(
                getattr(self, "_loaded_cache_key", ""),
                "gguf", "alex_minimax_model",
                offload_after_used=bool(self.settings.get("offload_after_used", False)),
            )


def local_model_inputs():
    """Shared INPUT_TYPES fragment for every *_local node."""
    return {
        "🤖本地GGUF模型": (local_model_options(), {}),
        "🖼️mmproj视觉投影": (local_mmproj_options(), {"default": "auto"}),
        "📐本地上下文长度": ("INT", {"default": 16384, "min": 512, "max": 131072, "step": 512}),
        "🎮GPU层数(-1=全部)": ("INT", {"default": -1, "min": -1, "max": 999}),
        "🔢图像最小token": ("INT", {"default": 1024, "min": 1, "max": 4096}),
        "🔢图像最大token": ("INT", {"default": 4096, "min": 1, "max": 8192}),
        "🔁重复惩罚": ("FLOAT", {
            "default": 1.1, "min": 1.0, "max": 2.0, "step": 0.01,
            "tooltip": "抑制复读/空行循环。H3长结构化输出用4B级小模型时建议1.1–1.3。",
        }),
        "🎲Top_K": ("INT", {"default": 20, "min": 0, "max": 200}),
        "🎲Min_P": ("FLOAT", {"default": 0.05, "min": 0.0, "max": 1.0, "step": 0.01}),
        "📌常驻显存不卸载": ("BOOLEAN", {"default": False, "tooltip": "固定该模型在缓存中，多个节点共用不重载。"}),
        "🧹推理后卸载模型": ("BOOLEAN", {"default": False, "tooltip": "本次推理结束后立即释放显存，给后续生图/视频节点让位。"}),
    }


def local_settings_from_kwargs(kwargs):
    return {
        "model_file": kwargs["🤖本地GGUF模型"],
        "mmproj_file": kwargs["🖼️mmproj视觉投影"],
        "n_ctx": int(kwargs["📐本地上下文长度"]),
        "n_gpu_layers": int(kwargs["🎮GPU层数(-1=全部)"]),
        "image_min_tokens": int(kwargs["🔢图像最小token"]),
        "image_max_tokens": int(kwargs["🔢图像最大token"]),
        "repeat_penalty": float(kwargs.get("🔁重复惩罚", 1.1)),
        "top_k": int(kwargs.get("🎲Top_K", 20)),
        "min_p": float(kwargs.get("🎲Min_P", 0.05)),
        "model_loaded_permanently": bool(kwargs.get("📌常驻显存不卸载", False)),
        "offload_after_used": bool(kwargs.get("🧹推理后卸载模型", False)),
    }
