"""Remote OpenAI-compatible backend for every alex_XXXX_API node.

Follows the approach of the user's comfyui-alex-node-llm-api
(`Alex LLM API (Unified)`): enter api key + endpoint, click "Refresh Models"
on the node, and the model dropdown is filled from the endpoint's /models
list and persisted per-endpoint on disk. The api key falls back to the
OPENAI_API_KEY environment variable, and a free-text custom_model overrides
the dropdown.
"""

import json
import os
import threading

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_HERE, "..", "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "models.json")

DEFAULT_ENDPOINT = "https://api.openai.com/v1"

DEFAULT_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o3-mini",
    "o4-mini",
    "deepseek-chat",
    "deepseek-reasoner",
    "qwen-vl-max",
    "qwen-vl-plus",
]

_lock = threading.Lock()
_cache = {}


def normalize_endpoint(endpoint):
    ep = (endpoint or "").strip().rstrip("/")
    return ep or DEFAULT_ENDPOINT


def _load():
    global _cache
    try:
        if os.path.isfile(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                _cache = {key: [str(model) for model in value]
                          for key, value in data.items() if isinstance(value, list)}
    except Exception as exc:  # pragma: no cover
        print(f"[AlexMiniMax-API] could not load model cache: {exc}")


def _save():
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_cache, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
    except Exception as exc:  # pragma: no cover
        print(f"[AlexMiniMax-API] could not save model cache: {exc}")


def _parse_models_payload(payload):
    models = []
    if isinstance(payload, dict):
        items = payload.get("data")
        if items is None:
            items = payload.get("models")
        if items is None and payload.get("object") == "list":
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        items = None
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, str) and item.strip():
            models.append(item.strip())
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
            if isinstance(model_id, str) and model_id.strip():
                models.append(model_id.strip())
    return sorted(dict.fromkeys(models))


def fetch_models(endpoint, api_key, timeout=30):
    ep = normalize_endpoint(endpoint)
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("列出模型需要API密钥（或设置 OPENAI_API_KEY 环境变量）。")
    url = f"{ep}/models"
    response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    try:
        payload = response.json()
    except Exception:
        raise RuntimeError(f"GET {url} -> HTTP {response.status_code}，非JSON响应：{response.text[:300]}")
    if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("error")):
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error, ensure_ascii=False)
        raise RuntimeError(f"GET {url} -> HTTP {response.status_code}: {error or response.text[:300]}")
    models = _parse_models_payload(payload)
    if not models:
        raise RuntimeError(f"GET {url} 未返回任何模型（端点可能不支持 /models）。")
    with _lock:
        _cache[ep] = models
        _save()
    print(f"[AlexMiniMax-API] refreshed {len(models)} model(s) from {url}")
    return models


def get_cached_models():
    with _lock:
        merged = []
        for models in _cache.values():
            merged.extend(models)
    return sorted(dict.fromkeys(merged))


def get_model_options():
    models = get_cached_models()
    return models if models else list(DEFAULT_MODELS)


def get_cache_snapshot():
    with _lock:
        return {key: list(value) for key, value in _cache.items()}


_load()


# ------------------------------------------------------------
# Chat client with friendly error labels (llama_Dapao style)
# ------------------------------------------------------------

def _response_error(response):
    text = response.text[:1200]
    try:
        data = response.json()
    except Exception:
        return text
    if not isinstance(data, dict):
        return text
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or error.get("code") or text)
    return str(data.get("message") or data.get("msg") or error or text)


class OpenAICompatClient:
    def __init__(self, api_key, endpoint, timeout):
        self.api_key = (api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("API密钥为空。请填写openai_api_key，或设置 OPENAI_API_KEY 环境变量。")
        self.endpoint = normalize_endpoint(endpoint)
        self.timeout = int(timeout)

    def chat(self, payload):
        url = f"{self.endpoint}/chat/completions"
        # Some OpenAI-compatible proxies reject unknown fields; seed only
        # controls local sampling, so it is not forwarded (llama_Dapao parity).
        payload = {key: value for key, value in payload.items() if key != "seed"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ComfyUI-alex-node-minimax/AlexLLM",
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except (requests.ConnectionError, requests.Timeout) as error:
            raise RuntimeError(
                f"无法连接 {url}：{error}。请检查endpoint地址与网络；请求不会自动重试，以免重复扣费。"
            ) from error
        if response.status_code >= 400:
            labels = {
                400: "请求参数错误",
                401: "API密钥无效或认证失败",
                402: "账户余额不足",
                403: "当前密钥没有该模型权限",
                404: "模型不存在（可点击节点上的刷新模型按钮）",
                429: "请求过于频繁，请稍后重试",
                500: "服务端处理异常，请稍后重试或切换模型",
                502: "上游模型暂时不可用",
                503: "模型服务暂时繁忙",
            }
            raise RuntimeError(
                f"{labels.get(response.status_code, '请求失败')} {response.status_code}：{_response_error(response)}"
            )
        try:
            return response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError(f"端点返回内容不是JSON：{response.text[:500]}") from error


def api_model_inputs():
    """Shared INPUT_TYPES fragment for every alex_XXXX_API node."""
    models = get_model_options()
    return {
        "🔑 openai_api_key": ("STRING", {
            "default": "", "multiline": False, "password": True,
            "tooltip": "OpenAI兼容端点密钥；留空时回退到 OPENAI_API_KEY 环境变量。密钥不写入配置文件。",
        }),
        "🌐 endpoint": ("STRING", {
            "default": DEFAULT_ENDPOINT, "multiline": False,
            "tooltip": "OpenAI兼容基址（含 /v1）。节点上的“刷新模型”按钮会读取该端点的 /models 列表。",
        }),
        "🤖 model": (models, {"default": models[0]}),
        "✍️ custom_model": ("STRING", {
            "default": "", "multiline": False,
            "tooltip": "非空时覆盖下拉选择，可直接填写端点上的任意模型ID。",
        }),
        "⌛ 请求超时(秒)": ("INT", {"default": 300, "min": 10, "max": 1800, "step": 10}),
    }


def api_client_from_kwargs(kwargs):
    return OpenAICompatClient(kwargs.get("🔑 openai_api_key", ""), kwargs.get("🌐 endpoint", ""),
                              kwargs.get("⌛ 请求超时(秒)", 300))


def api_model_from_kwargs(kwargs):
    final_model = (kwargs.get("✍️ custom_model") or "").strip() or kwargs.get("🤖 model", "")
    if not final_model:
        raise ValueError("未选择模型：请选择model下拉项或使用custom_model。")
    return final_model
