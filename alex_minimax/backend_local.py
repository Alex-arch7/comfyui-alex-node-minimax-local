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
import os
import threading
import time

import folder_paths

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
        for obj in entry["resources"].values():
            if hasattr(obj, "close"):
                try:
                    obj.close()
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

    def _ensure_model(self, payload):
        settings = self.settings
        max_tokens = int(payload.get("max_tokens", 1024))
        image_count = _payload_image_count(payload.get("messages", []))
        n_ctx = int(settings["n_ctx"])
        if image_count:
            required = int(settings["image_max_tokens"]) * image_count + max_tokens + 512
            if required > 131072:
                raise ValueError(
                    "当前图片数量、图像最大token与输出token需要超过131072上下文。"
                    "请减少图片数量、图像最大token或最大输出令牌。"
                )
            n_ctx = max(n_ctx, required)

        gguf_path = resolve_gguf_path(settings["model_file"])
        if not gguf_path or not os.path.isfile(gguf_path):
            raise FileNotFoundError(
                f"未找到GGUF模型文件：{settings['model_file']}。请将模型放入 ComfyUI/models/LLM/ 目录。"
            )
        mmproj_path = resolve_mmproj_path(settings["mmproj_file"], settings["model_file"])
        if image_count and not mmproj_path:
            raise ValueError("请求包含图片/视频帧，但该节点没有解析到mmproj视觉投影，请选择匹配的mmproj。")

        cache_key = f"{gguf_path}|ctx{n_ctx}|mmproj{mmproj_path}"

        def load_model():
            llm_kwargs = {
                "model_path": gguf_path,
                "n_gpu_layers": int(settings.get("n_gpu_layers", -1)),
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

        return model_cache.get(
            cache_key, "gguf", "alex_minimax_model", load_model,
            pinned=bool(settings.get("model_loaded_permanently", False)),
        )["model"]

    def chat(self, payload):
        llm = self._ensure_model(payload)
        try:
            return llm.create_chat_completion(
                messages=payload.get("messages", []),
                temperature=float(payload.get("temperature", 0.4)),
                max_tokens=int(payload.get("max_tokens", 1024)),
                top_p=float(payload.get("top_p", 1.0)),
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
            model_cache.release(
                f"{resolve_gguf_path(self.settings['model_file'])}|ctx{llm.n_ctx}|mmproj"
                f"{resolve_mmproj_path(self.settings['mmproj_file'], self.settings['model_file'])}",
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
        "model_loaded_permanently": bool(kwargs.get("📌常驻显存不卸载", False)),
        "offload_after_used": bool(kwargs.get("🧹推理后卸载模型", False)),
    }
