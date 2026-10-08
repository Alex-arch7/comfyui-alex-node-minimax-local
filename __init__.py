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

from .nodes_h3 import NODE_CLASS_MAPPINGS as H3_NODES, NODE_DISPLAY_NAME_MAPPINGS as H3_NAMES
from .nodes_music3 import NODE_CLASS_MAPPINGS as MUSIC3_NODES, NODE_DISPLAY_NAME_MAPPINGS as MUSIC3_NAMES
from .nodes_qwen_image import (
    NODE_CLASS_MAPPINGS as QWEN_IMAGE_NODES,
    NODE_DISPLAY_NAME_MAPPINGS as QWEN_IMAGE_NAMES,
)

NODE_CLASS_MAPPINGS = {**H3_NODES, **MUSIC3_NODES, **QWEN_IMAGE_NODES}
NODE_DISPLAY_NAME_MAPPINGS = {**H3_NAMES, **MUSIC3_NAMES, **QWEN_IMAGE_NAMES}

WEB_DIRECTORY = "./web"

try:
    from .api import register_routes

    register_routes()
except Exception as _exc:  # pragma: no cover
    print(f"[AlexMiniMax] failed to register HTTP routes: {_exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
