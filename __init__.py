"""comfyui-alex-node-minimax-local

MiniMax H3 / Music 3 prompt compilers plus Qwen-Image-2.1 prompt rewriting,
with paired local and remote backends:

  * alex_XXXX_local — local GGUF via llama-cpp-python with a multimodal
    chat_handler and a shared pinned/LRU model cache (the approach of
    ComfyUI_qwen_chat_models' alex_qwen_VL_model / alex_qwen_chat_model).
  * alex_XXXX_API — OpenAI-compatible endpoint with api key + endpoint +
    refreshable model dropdown (the approach of comfyui-alex-node-llm-api's
    Alex LLM API (Unified)).

The frontend keeps the llama_Dapao core value: it detects the official
MiniMax H3 nodes downstream, locks the real asset numbering, and offers
@-material references.
"""

import importlib
import traceback

_MODULE_ERRORS = {}
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

for _module_name in ("nodes_h3", "nodes_h3_skill", "nodes_music3", "nodes_qwen_image"):
    try:
        _module = importlib.import_module(f".{_module_name}", __name__)
        NODE_CLASS_MAPPINGS.update(_module.NODE_CLASS_MAPPINGS)
        NODE_DISPLAY_NAME_MAPPINGS.update(_module.NODE_DISPLAY_NAME_MAPPINGS)
    except Exception as _exc:
        _MODULE_ERRORS[_module_name] = _exc
        print(f"[AlexMiniMax] ❌ import failed in {_module_name}:")
        traceback.print_exc()

if _MODULE_ERRORS:
    print(f"[AlexMiniMax] {len(_MODULE_ERRORS)} module(s) failed to import; "
          "the traceback above shows the exact cause. Nodes from healthy modules are still registered.")
else:
    print("[AlexMiniMax] nodes imported: " + ", ".join(sorted(NODE_CLASS_MAPPINGS)))

WEB_DIRECTORY = "./web"

try:
    from .api import register_routes

    register_routes()
except Exception as _exc:  # pragma: no cover
    print(f"[AlexMiniMax] failed to register HTTP routes: {_exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
