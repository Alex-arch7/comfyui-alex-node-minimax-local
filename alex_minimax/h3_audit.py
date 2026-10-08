"""Deterministic audits for MiniMax H3 prompts and reference manifests.

Adapted from ComfyUI-llama_Dapao (h3_video_prompt_node.py). These checks are
the project's core value: the LLM output must satisfy the official H3 field
order, alignment-sentence templates, timestamp bounds and stable asset labels,
otherwise the node refuses or annotates the result instead of silently
producing a misaligned prompt.
"""

import json
import re

def audit_h3_prompt(prompt, mode, duration, image_count, video_count, audio_count):
    issues = []
    text = str(prompt or "").strip()
    fields = (
        [
            "subject_definitions:",
            "summary:",
            "retention_analysis:",
            "detailed_description:",
            "overall_soundscape:",
            "non_diegetic_music:",
        ]
        if mode == "Ref2VA"
        else ["integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"]
    )
    positions = [text.find(field) for field in fields]
    missing = [field for field, position in zip(fields, positions) if position < 0]
    if missing:
        issues.append("缺少H3固定字段：" + "、".join(missing))
    elif positions != sorted(positions):
        issues.append("H3固定字段顺序不符合官方规范。")

    if mode == "I2VA":
        required = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
        if not text.startswith(required):
            issues.append("I2VA首帧对齐句未采用官方固定格式。")
    elif mode == "FL2VA":
        if not text.startswith("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark"):
            issues.append("FL2VA首尾帧对齐句未采用官方固定格式。")
        if f"{duration:.2f}-second mark" not in text[:500]:
            issues.append(f"FL2VA对齐句未把尾帧锁定在{duration:.2f}秒。")
    elif mode == "L2VA":
        if not text.startswith("How the reference pictures align with the target video — <Picture 1> (from [Shot"):
            issues.append("L2VA尾帧对齐句未采用官方固定格式。")
        if f"{duration:.2f}-second mark" not in text[:400]:
            issues.append(f"L2VA对齐句未把尾帧锁定在{duration:.2f}秒。")

    for minute, second, millisecond in re.findall(r"\bAt\s+(\d{2}):(\d{2})\.(\d{3})", text):
        timestamp = int(minute) * 60 + int(second) + int(millisecond) / 1000.0
        if timestamp >= duration:
            issues.append(f"镜头切点{minute}:{second}.{millisecond}超出或等于目标时长{duration:.2f}秒。")

    if mode == "Ref2VA":
        expected = {"Picture": image_count, "Video": video_count, "Audio": audio_count}
        for label, count in expected.items():
            used = {int(value) for value in re.findall(rf"<{label}\s+(\d+)>", text)}
            out_of_range = sorted(number for number in used if number < 1 or number > count)
            if out_of_range:
                issues.append(f"出现素材清单中不存在的<{label} N>编号：{out_of_range}。")
            missing_numbers = [number for number in range(1, count + 1) if number not in used]
            if missing_numbers:
                issues.append(f"未在Ref2VA提示词中引用{label}素材：{missing_numbers}。")
    elif re.search(r"<(Video|Audio)\s+\d+>", text):
        issues.append(f"{mode}基础模式不应出现<Video N>或<Audio N>引用。")
    return issues


def parse_reference_manifest(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("H3素材标记格式无效，请重新连接H3专用提示词框。") from error
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError("H3素材标记缺少有效items字段。")

    limits = {"Picture": 9, "Video": 3, "Audio": 6}
    next_index = {kind: 1 for kind in limits}
    items = []
    for raw in value["items"]:
        if not isinstance(raw, dict):
            raise ValueError("H3素材标记包含无效项目。")
        kind = str(raw.get("kind") or "")
        index = raw.get("index")
        if kind not in limits or not isinstance(index, int):
            raise ValueError("H3素材标记包含未知素材类型或编号。")
        if index != next_index[kind] or index > limits[kind]:
            raise ValueError(f"H3素材标记中的{kind}编号不连续或超出官方上限。")
        next_index[kind] += 1
        token = f"<{kind} {index}>"
        if raw.get("token") not in (None, token):
            raise ValueError(f"H3素材标记必须使用官方格式：{token}")
        items.append({
            "kind": kind,
            "index": index,
            "token": token,
            "label": str(raw.get("label") or token),
            "source_input": str(raw.get("source_input") or ""),
        })

    mode = str(value.get("mode") or "T2VA")
    if mode not in {"T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"}:
        raise ValueError(f"H3素材标记包含未知模式：{mode}")
    counts = {kind: sum(item["kind"] == kind for item in items) for kind in limits}
    if mode == "T2VA" and items:
        raise ValueError("T2VA素材标记不应包含参考素材。")
    if mode in {"I2VA", "L2VA"} and counts != {"Picture": 1, "Video": 0, "Audio": 0}:
        raise ValueError(f"{mode}素材标记必须只包含<Picture 1>。")
    if mode == "FL2VA" and counts != {"Picture": 2, "Video": 0, "Audio": 0}:
        raise ValueError("FL2VA素材标记必须包含<Picture 1>和<Picture 2>。")
    if mode == "Ref2VA" and counts["Audio"] and not (counts["Picture"] or counts["Video"]):
        raise ValueError("Ref2VA音频不能作为唯一参考素材。")
    return {"version": 1, "mode": mode, "target": str(value.get("target") or ""), "items": items, "counts": counts}


def audit_reference_manifest(prompt, manifest):
    if not manifest:
        return []
    expected = {item["token"] for item in manifest["items"]}
    used = {f"<{kind} {number}>" for kind, number in re.findall(r"<(Picture|Video|Audio)\s+(\d+)>", str(prompt or ""))}
    issues = []
    missing = sorted(expected - used)
    unexpected = sorted(used - expected)
    if missing:
        issues.append("缺少官方素材标记：" + "、".join(missing))
    if unexpected:
        issues.append("出现未连接的官方素材标记：" + "、".join(unexpected))
    return issues
