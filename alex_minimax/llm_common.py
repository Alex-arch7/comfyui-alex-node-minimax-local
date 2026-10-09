"""Shared LLM response helpers (OpenAI-compatible shapes).

Adapted from ComfyUI-llama_Dapao (h3_video_prompt_node.py).
"""

import json
import re
import sys

def safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        printable = str(message).encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(printable)


def response_error(response):
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

def content_text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        value = item.get("text") or item.get("output_text")
        if isinstance(value, dict):
            value = value.get("value") or value.get("text")
        if value:
            texts.append(str(value))
    return "\n".join(texts)


def extract_text(result):
    if not isinstance(result, dict):
        return ""
    choices = result.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        text = content_text(message.get("content"))
        if text:
            return text
        if first.get("text") is not None:
            return str(first["text"])
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    output = result.get("output")
    if isinstance(output, list):
        texts = [content_text(item.get("content")) for item in output if isinstance(item, dict)]
        return "\n".join(text for text in texts if text)
    return ""


def sanitized_result(value):
    if isinstance(value, dict):
        return {key: sanitized_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitized_result(item) for item in value]
    if isinstance(value, str) and value.startswith("data:") and len(value) > 200:
        return f"<Data URI已省略，共{len(value)}字符>"
    return value


def extract_finish_reason(result):
    if not isinstance(result, dict):
        return ""
    choices = result.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return str(choices[0].get("finish_reason") or "")
    return ""


_BLANK_RUN_PATTERN = re.compile(r"\n{3,}")


def collapse_blank_runs(text):
    """Collapse repetition-loop blank runs (\\n{3,}) into a single blank line.

    Small local models sometimes fall into a newline repetition loop in long
    structured outputs; returns (cleaned_text, removed_char_count).
    """
    original = str(text or "")
    cleaned, _count = _BLANK_RUN_PATTERN.subn("\n\n", original)
    cleaned = cleaned.strip()
    return cleaned, len(original) - len(cleaned)


_H3_FIELD_ORDER = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
    "integrated_multimodal_description",
)


def render_h3_prompt_dict(data):
    """Render a dict-shaped H3 structure into the official field-per-line text.

    Small models sometimes return h3_prompt as a nested JSON object (or skip
    the wrapper entirely and put the six fields at top level). str(dict) would
    produce an unreadable single-line Python repr, so fields are re-emitted in
    official order with real newlines, and semicolon-separated
    subject/retention lists are split onto their own lines.
    """
    keys = [key for key in _H3_FIELD_ORDER if key in data]
    keys += [key for key in data if key not in _H3_FIELD_ORDER]
    blocks = []
    for key in keys:
        value = data[key]
        if isinstance(value, (list, tuple)):
            text = "\n".join(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            text = "\n".join(f"{item_key}: {item_value}" for item_key, item_value in value.items())
        else:
            text = str(value or "").strip()
        if key in ("subject_definitions", "retention_analysis") and text:
            parts = [part.strip() for part in re.split(r";\s*", text) if part.strip()]
            if len(parts) > 1:
                text = "\n".join(parts)
        blocks.append(f"{key}:\n{text}")
    return "\n\n".join(blocks)


def parse_h3_compiler_output(text, fallback_mode):
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(cleaned[index:])
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(parsed, dict):
        return {
            "mode": fallback_mode,
            "h3_prompt": cleaned,
            "material_analysis": "模型未返回结构化素材分析。",
            "production_notes": "模型返回内容未采用JSON封装，已将完整文本作为H3提示词输出。",
        }
    raw_prompt = parsed.get("h3_prompt") or parsed.get("prompt")
    if isinstance(raw_prompt, dict):
        h3_text = render_h3_prompt_dict(raw_prompt)
    elif isinstance(raw_prompt, str):
        h3_text = raw_prompt.strip()
    else:
        # Wrapper missing: the object itself may already be the H3 structure.
        field_keys = [key for key in parsed if key in _H3_FIELD_ORDER]
        h3_text = render_h3_prompt_dict(parsed) if field_keys else ""
    return {
        "mode": str(parsed.get("mode") or fallback_mode).strip(),
        "h3_prompt": h3_text,
        "material_analysis": str(parsed.get("material_analysis") or "").strip(),
        "production_notes": str(parsed.get("production_notes") or "").strip(),
    }
