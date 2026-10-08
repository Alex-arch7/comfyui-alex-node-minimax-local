#!/usr/bin/env python
"""One-command import diagnosis for comfyui-alex-node-minimax-local.

Run this INSIDE the ComfyUI machine's Python environment (the same interpreter
ComfyUI uses, e.g. `conda activate cu130`):

    python /path/to/custom_nodes/comfyui-alex-node-minimax-local/diagnose.py

It mimics ComfyUI's custom-node import and prints the FULL traceback of the
first failing step, plus environment facts (python, llama_cpp, requests,
numpy, PIL, aiohttp). Paste the output back if the cause is unclear.
"""

import importlib
import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def section(title):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


section("1) environment")
print("python:", sys.version.replace("\n", " "))
print("executable:", sys.executable)
print("plugin dir:", HERE)

parent = os.path.dirname(HERE)
comfy_root = os.path.dirname(parent) if os.path.basename(parent) == "custom_nodes" else ""
if comfy_root:
    print("ComfyUI root detected:", comfy_root)
    sys.path.insert(0, comfy_root)
else:
    print("WARNING: plugin is not under a custom_nodes/ directory; "
          "folder_paths/server may not be importable.")

section("2) dependency imports")
for name in ("torch", "numpy", "PIL", "requests", "aiohttp", "folder_paths", "server"):
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", "-")
        print(f"  OK   {name} ({version})")
    except Exception as exc:
        print(f"  FAIL {name}: {type(exc).__name__}: {exc}")

try:
    import llama_cpp
    print(f"  OK   llama_cpp ({getattr(llama_cpp, '__version__', '?')})")
    from llama_cpp import Llama  # noqa: F401
    print("  OK   llama_cpp.Llama")
    import llama_cpp.llama_chat_format as fmt
    handlers = [n for n in ("Qwen3VLChatHandler", "Qwen25VLChatHandler", "Qwen2VLChatHandler",
                            "Llava15ChatHandler", "LlavaChatHandler") if hasattr(fmt, n)]
    print(f"  vision chat_handlers available: {handlers or 'NONE (text-only GGUF only)'}")
except Exception as exc:
    print(f"  FAIL llama_cpp: {type(exc).__name__}: {exc}")
    traceback.print_exc()

section("3) plugin package import (same as ComfyUI)")
try:
    import folder_paths  # noqa: F401
    print("folder_paths OK, models_dir =", folder_paths.models_dir)
except Exception:
    print("folder_paths unavailable — injecting a stub so the package can still be import-tested")
    import types
    stub = types.ModuleType("folder_paths")
    stub.models_dir = os.path.join(comfy_root or ".", "models")
    stub.get_filename_list = lambda key: []
    sys.modules["folder_paths"] = stub

try:
    spec = importlib.util.spec_from_file_location(
        "comfyui_alex_node_minimax_local", os.path.join(HERE, "__init__.py"),
        submodule_search_locations=[HERE],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["comfyui_alex_node_minimax_local"] = package
    spec.loader.exec_module(package)
    nodes = sorted(getattr(package, "NODE_CLASS_MAPPINGS", {}))
    print("package import OK; registered nodes:")
    for node_id in nodes:
        print("  -", node_id)
    if not nodes:
        print("!! NODE_CLASS_MAPPINGS is EMPTY — see tracebacks printed above")
        sys.exit(2)
except Exception:
    print("package import FAILED with:")
    traceback.print_exc()
    sys.exit(1)

print("\n✅ diagnosis finished without fatal errors")
