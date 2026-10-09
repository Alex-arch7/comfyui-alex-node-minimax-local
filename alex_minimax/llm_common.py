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
    return {
        "mode": str(parsed.get("mode") or fallback_mode).strip(),
        "h3_prompt": str(parsed.get("h3_prompt") or parsed.get("prompt") or "").strip(),
        "material_analysis": str(parsed.get("material_analysis") or "").strip(),
        "production_notes": str(parsed.get("production_notes") or "").strip(),
    }
