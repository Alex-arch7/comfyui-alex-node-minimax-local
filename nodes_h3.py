"""MiniMax H3 video prompt compiler nodes.

Core value ported from ComfyUI-llama_Dapao: a deterministic ComfyUI surface
for the official MiniMax-H3 h3-prompt-writing skill. The node compiles the
user's request plus ordered reference images / video frame
batches / audio into one production-ready H3 Context-IR prompt, then audits
field order, alignment sentences, timestamps and stable asset labels. It does
not submit video-generation jobs; the prompt connects to the official
MiniMax H3 nodes.

Two backends share one engine:
  * alex_h3_prompt_local — local GGUF via llama-cpp-python (alex_qwen_VL_model style)
  * alex_h3_prompt_API   — OpenAI-compatible endpoint (Alex LLM API Unified style)
"""

import asyncio
import json
import re
import time
import traceback

from .alex_minimax import h3_spec
from .alex_minimax.h3_audit import audit_h3_prompt, parse_reference_manifest, audit_reference_manifest
from .alex_minimax import media
from .alex_minimax.llm_common import (
    safe_print, extract_text, sanitized_result, parse_h3_compiler_output,
    collapse_blank_runs, extract_finish_reason,
)
from .alex_minimax.backend_local import local_model_inputs, local_settings_from_kwargs, LocalLLMClient
from .alex_minimax.backend_api import api_model_inputs, api_client_from_kwargs, api_model_from_kwargs

NODE_CATEGORY = "Alex/MiniMax/H3"

MODE_OPTIONS = h3_spec.MODE_OPTIONS
STYLE_OPTIONS = h3_spec.STYLE_OPTIONS
ASPECT_RATIO_OPTIONS = h3_spec.ASPECT_RATIO_OPTIONS
MAX_H3_IMAGES = h3_spec.MAX_H3_IMAGES
MAX_H3_VIDEOS = h3_spec.MAX_H3_VIDEOS
MAX_H3_AUDIOS = h3_spec.MAX_H3_AUDIOS
MAX_H3_MIXED_FILES = h3_spec.MAX_H3_MIXED_FILES


def business_inputs():
    """INPUT_TYPES fragment shared by both H3 compiler nodes."""
    optional = {
        "🧩 H3素材标记": ("DAPAO_H3_REFERENCES", {
            "tooltip": "连接alex_h3_prompt_box的素材标记输出，用官方H3节点的实际素材顺序锁定编号。",
        }),
        "🔗 外部文本输入": ("STRING", {
            "forceInput": True, "default": "",
            "tooltip": "连接任意STRING文本节点；连接后执行时优先使用外部文本，未连接时使用本节点的大文本框。",
        }),
        "🎬 首帧图": ("IMAGE", {"tooltip": "I2VA/FL2VA 使用；在H3提示词中作为精确首帧锚点。"}),
        "🏁 尾帧图": ("IMAGE", {"tooltip": "L2VA/FL2VA 使用；在H3提示词中作为精确尾帧锚点。"}),
        "🎬 参考视频帧率": ("FLOAT", {
            "default": 24.0, "min": 1.0, "max": 120.0, "step": 0.5,
            "tooltip": "参考视频IMAGE帧批次按该帧率解释时长；读取视频节点请与之一致（常见24/30fps）。",
        }),
        "🎞️ 视频每秒采样帧数": ("INT", {
            "default": 2, "min": 1, "max": 8,
            "tooltip": "每秒采样多少帧送入LLM分析；帧越多理解越细，上下文占用也越大。",
        }),
        "🎧 参考音频原声直传LLM": ("BOOLEAN", {
            "default": False,
            "tooltip": "把参考音频1/2/3接口的原始WAV一并送入LLM（input_audio）；要求所选模型支持音频输入。",
        }),
        "🚫 出错时跳过": ("BOOLEAN", {"default": False}),
    }
    for index in range(1, MAX_H3_IMAGES + 1):
        optional[f"🖼️ 参考图{index}"] = ("IMAGE", {"tooltip": f"Ref2VA源图片{index}；源图片总数最多{MAX_H3_IMAGES}张。"})
    for index in range(1, MAX_H3_VIDEOS + 1):
        optional[f"🎞️ 参考视频{index}"] = ("IMAGE", {
            "tooltip": f"Ref2VA源视频{index}；连接IMAGE帧批次，按“参考视频帧率”解释；每个2–15秒，视频总时长不超过15秒。",
        })
        optional[f"🎵 参考音频{index}"] = ("AUDIO", {
            "tooltip": f"Ref2VA源音频{index}；每个2–15秒，音频总时长不超过15秒，不能作为唯一素材。",
        })
    return {
        "required": {
            "🎛️ H3生成模式": (MODE_OPTIONS, {"default": "自动识别"}),
            "🎨 创作类型": (STYLE_OPTIONS, {"default": "通用H3"}),
            "🌐 输出中文提示词": ("BOOLEAN", {
                "default": False,
                "tooltip": "默认关闭时输出英文H3提示词；开启后正文输出简体中文，H3固定字段和标签仍保留官方格式。",
            }),
            "📝 原始视频需求": ("STRING", {
                "multiline": True,
                "default": "电影感镜头，主体动作自然，音画同步，画面稳定且细节丰富。",
                "placeholder": "用自然语言描述你想生成的视频……",
            }),
            "🧩 H3自动素材清单": ("STRING", {
                "multiline": True, "default": "",
                "tooltip": "由节点界面在最终提示词直连官方MiniMax H3节点时自动维护。",
            }),
            "⏱️ 目标时长(秒)": ("INT", {"default": 5, "min": 4, "max": 15, "step": 1}),
            "📐 视频比例": (ASPECT_RATIO_OPTIONS, {"default": "16:9"}),
            "🔊 原生音频": ("BOOLEAN", {"default": True}),
            "🌡️ 温度": ("FLOAT", {"default": 0.4, "min": 0.0, "max": 2.0, "step": 0.01}),
            "📝 最大输出令牌": ("INT", {"default": 4096, "min": 512, "max": 65536, "step": 1}),
            "🎲 Top_P": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "🎲 随机种": ("INT", {
                "default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                "control_after_generate": "randomize",
                "tooltip": "本地后端会作为llama.cpp采样种子；API后端仅控制ComfyUI缓存。",
            }),
        },
        "optional": optional,
    }


class H3CompilerEngine:
    """All business logic; the backend is injected as a client with .chat(payload)."""

    @staticmethod
    def _collect_images(kwargs):
        ordered = []
        first = kwargs.get("🎬 首帧图")
        last = kwargs.get("🏁 尾帧图")
        if first is not None:
            if first.shape[0] != 1:
                raise ValueError(f"首帧图只能包含1张图片，当前批次为{first.shape[0]}张。")
            for uri in media.tensor_to_data_uris(first):
                ordered.append(("首帧图", uri))
        if last is not None:
            if last.shape[0] != 1:
                raise ValueError(f"尾帧图只能包含1张图片，当前批次为{last.shape[0]}张。")
            for uri in media.tensor_to_data_uris(last):
                ordered.append(("尾帧图", uri))
        for slot in range(1, MAX_H3_IMAGES + 1):
            image = kwargs.get(f"🖼️ 参考图{slot}")
            if image is None:
                continue
            for batch_index, uri in enumerate(media.tensor_to_data_uris(image), start=1):
                suffix = f"-{batch_index}" if image.shape[0] > 1 else ""
                ordered.append((f"参考图{slot}{suffix}", uri))
        if len(ordered) > MAX_H3_IMAGES:
            raise ValueError(f"H3最多支持{MAX_H3_IMAGES}张图片，当前检测到{len(ordered)}张。")
        return ordered

    @staticmethod
    def _collect_video_audio(kwargs):
        fps = float(kwargs.get("🎬 参考视频帧率", 24.0) or 24.0)
        sample_frames_per_second = int(kwargs.get("🎞️ 视频每秒采样帧数", 2) or 2)
        include_raw_audio = bool(kwargs.get("🎧 参考音频原声直传LLM", False))
        videos = []
        audios = []
        for slot in range(1, MAX_H3_VIDEOS + 1):
            video = kwargs.get(f"🎞️ 参考视频{slot}")
            if video is None:
                continue
            info = media.analyze_video_tensor(video, len(videos) + 1, fps, sample_frames_per_second)
            info["slot"] = slot
            videos.append(info)
        for slot in range(1, MAX_H3_AUDIOS + 1):
            audio = kwargs.get(f"🎵 参考音频{slot}")
            if audio is None:
                continue
            info = media.analyze_audio(audio, len(audios) + 1, include_raw_audio)
            info["slot"] = slot
            audios.append(info)
        return videos, audios

    @staticmethod
    def _validate_source_limits(ordered_images, videos, audios):
        if len(ordered_images) > MAX_H3_IMAGES:
            raise ValueError(f"Ref2VA最多支持{MAX_H3_IMAGES}张源图片。")
        if len(videos) > MAX_H3_VIDEOS:
            raise ValueError(f"Ref2VA最多支持{MAX_H3_VIDEOS}个源视频。")
        if len(audios) > MAX_H3_AUDIOS:
            raise ValueError(f"Ref2VA最多支持{MAX_H3_AUDIOS}个源音频。")
        file_count = len(ordered_images) + len(videos) + len(audios)
        if file_count > MAX_H3_MIXED_FILES:
            raise ValueError(
                f"Ref2VA图片、视频和音频合计最多{MAX_H3_MIXED_FILES}个文件，"
                f"当前为{file_count}个（图片{len(ordered_images)}＋视频{len(videos)}＋音频{len(audios)}）。"
            )
        video_duration = sum(item["duration"] for item in videos)
        audio_duration = sum(item["duration"] for item in audios)
        if video_duration > h3_spec.MAX_MEDIA_TOTAL_DURATION + 0.05:
            raise ValueError(
                f"参考视频总时长为{video_duration:.2f}秒，H3要求不超过"
                f"{h3_spec.MAX_MEDIA_TOTAL_DURATION:.0f}秒。"
            )
        if audio_duration > h3_spec.MAX_MEDIA_TOTAL_DURATION + 0.05:
            raise ValueError(
                f"参考音频总时长为{audio_duration:.2f}秒，H3要求不超过"
                f"{h3_spec.MAX_MEDIA_TOTAL_DURATION:.0f}秒。"
            )
        if audios and not (ordered_images or videos):
            raise ValueError("H3参考音频不能作为唯一素材，必须同时接入至少一张图片或一个视频。")

    @staticmethod
    def _resolve_mode(selected, has_first, has_last, has_references, has_video_or_audio):
        manual = {
            "T2VA-文生视频": "T2VA",
            "I2VA-首帧生视频": "I2VA",
            "FL2VA-首尾帧生视频": "FL2VA",
            "L2VA-尾帧生视频": "L2VA",
            "Ref2VA-全能参考": "Ref2VA",
        }
        if selected != "自动识别":
            return manual[selected]
        if has_references or has_video_or_audio:
            return "Ref2VA"
        if has_first and has_last:
            return "FL2VA"
        if has_first:
            return "I2VA"
        if has_last:
            return "L2VA"
        return "T2VA"

    @staticmethod
    def _validate_mode(mode, has_first, has_last, has_references, has_video_or_audio):
        if mode == "T2VA" and (has_first or has_last or has_references or has_video_or_audio):
            raise ValueError("T2VA不使用参考素材；请选择自动识别或对应的图像/全能参考模式。")
        if mode == "I2VA" and not has_first:
            raise ValueError("I2VA必须接入首帧图。")
        if mode == "I2VA" and (has_last or has_references or has_video_or_audio):
            raise ValueError("I2VA只使用一张首帧图；检测到其他参考素材，请改用自动识别或Ref2VA。")
        if mode == "FL2VA" and (not has_first or not has_last):
            raise ValueError("FL2VA必须同时接入首帧图和尾帧图。")
        if mode == "FL2VA" and (has_references or has_video_or_audio):
            raise ValueError("FL2VA只使用首帧图和尾帧图；检测到其他参考素材，请改用自动识别或Ref2VA。")
        if mode == "L2VA" and not has_last:
            raise ValueError("L2VA必须接入尾帧图。")
        if mode == "L2VA" and (has_first or has_references or has_video_or_audio):
            raise ValueError("L2VA只使用一张尾帧图；检测到其他参考素材，请改用自动识别或Ref2VA。")
        if mode == "Ref2VA" and not (has_first or has_last or has_references or has_video_or_audio):
            raise ValueError("Ref2VA至少需要图片或参考视频素材；参考音频不能作为唯一素材。")

    @staticmethod
    def _build_user_content(kwargs, mode, style, ordered_images, videos, audios, reference_manifest=None):
        duration = int(kwargs.get("⏱️ 目标时长(秒)", 5))
        ratio = kwargs.get("📐 视频比例", "16:9")
        native_audio = bool(kwargs.get("🔊 原生音频", True))
        output_chinese = bool(kwargs.get("🌐 输出中文提示词", False))
        output_language = "Simplified Chinese" if output_chinese else "English"
        if reference_manifest:
            pictures = [item for item in reference_manifest["items"] if item["kind"] == "Picture"]
            manifest_videos = [item for item in reference_manifest["items"] if item["kind"] == "Video"]
            manifest_audios = [item for item in reference_manifest["items"] if item["kind"] == "Audio"]
            image_labels = [
                f"{item['token']}={ordered_images[item['index'] - 1][0] if item['index'] <= len(ordered_images) else item['label']}"
                for item in pictures
            ]
            video_labels = []
            for item in manifest_videos:
                detail = next((video for video in videos if video["index"] == item["index"]), None)
                if detail:
                    video_labels.append(
                        f"{item['token']}={item['label']}，已接入LLM分析素材，{detail['duration']:.2f}秒，"
                        f"{detail['width']}x{detail['height']}，{detail['fps']:.2f}fps"
                    )
                else:
                    video_labels.append(f"{item['token']}={item['label']}，仅按用户文字说明使用")
            audio_labels = []
            for item in manifest_audios:
                detail = next((audio for audio in audios if audio["index"] == item["index"]), None)
                if detail:
                    audio_labels.append(
                        f"{item['token']}={item['label']}，已接入LLM分析素材，{detail['duration']:.2f}秒，"
                        f"{detail['sample_rate']}Hz/{detail['channels']}声道，估算BPM={detail['bpm']:.1f}，"
                        f"RMS={detail['rms']:.4f}，静音比例={detail['silence_ratio']:.1%}"
                    )
                else:
                    audio_labels.append(f"{item['token']}={item['label']}，仅按用户文字说明使用")
            label_lock = (
                "AUTHORITATIVE OFFICIAL H3 LABEL LOCK:\n"
                f"Allowed labels in fixed identity order: {', '.join(item['token'] for item in reference_manifest['items']) or 'none'}\n"
                "Preserve every label character-for-character. Never rename, renumber, swap roles, omit a listed label, "
                "or invent another Picture/Video/Audio label. The user's text assigns each label's semantic role.\n"
            )
            mixed_count = len(reference_manifest["items"])
            audio_limit = 6
        else:
            image_labels = [f"<Picture {index}>={name}" for index, (name, _) in enumerate(ordered_images, start=1)]
            video_labels = [
                f"<Video {item['index']}>=参考视频{item['slot']}接口，{item['duration']:.2f}秒，"
                f"{item['width']}x{item['height']}，{item['fps']:.2f}fps"
                for item in videos
            ]
            audio_labels = [
                f"<Audio {item['index']}>=参考音频{item['slot']}接口，{item['duration']:.2f}秒，"
                f"{item['sample_rate']}Hz/{item['channels']}声道，估算BPM={item['bpm']:.1f}，"
                f"RMS={item['rms']:.4f}，静音比例={item['silence_ratio']:.1%}"
                for item in audios
            ]
            label_lock = ""
            mixed_count = len(image_labels) + len(video_labels) + len(audio_labels)
            audio_limit = MAX_H3_AUDIOS
        text = (
            f"Requested H3 mode: {mode}\n"
            f"Creative preset: {style}\n"
            "SELECTED CREATIVE CONTRACT (apply every applicable rule; the user's explicit request wins on creative facts):\n"
            f"{h3_spec.render_creative_profile(style)}\n"
            f"Output descriptive language: {output_language}\n"
            f"Exact duration: {duration}.00 seconds\n"
            f"Aspect ratio: {ratio}\n"
            f"Native audio enabled: {str(native_audio).lower()}\n"
            f"{label_lock}"
            "SOURCE MEDIA MANIFEST (source files only; analysis frames/spectrograms do not add files):\n"
            f"Images ({len(image_labels)}/{MAX_H3_IMAGES}): {', '.join(image_labels) if image_labels else 'none'}\n"
            f"Videos ({len(video_labels)}/{MAX_H3_VIDEOS}): {'; '.join(video_labels) if video_labels else 'none'}\n"
            f"Audio ({len(audio_labels)}/{audio_limit}): {'; '.join(audio_labels) if audio_labels else 'none'}\n"
            f"Reference label count: {mixed_count}\n\n"
            f"原始视频需求（素材角色、对白、歌词、画面文字和声音要求均以此处为准）：\n"
            f"{(kwargs.get('🔗 外部文本输入') or kwargs.get('📝 原始视频需求') or '').strip()}"
        )
        if not (ordered_images or videos or audios):
            return text
        content = [{"type": "text", "text": text}]
        for index, (name, uri) in enumerate(ordered_images, start=1):
            content.append({"type": "text", "text": f"Source <Picture {index}> ({name}) follows."})
            content.append({"type": "image_url", "image_url": {"url": uri}})
        for item in videos:
            for frame in item["frames"]:
                content.append({
                    "type": "text",
                    "text": (
                        f"Analysis artifact for <Video {item['index']}>: sampled frame at "
                        f"{frame['time']:.3f}s. This is not a <Picture N> source."
                    ),
                })
                content.append({"type": "image_url", "image_url": {"url": frame["uri"]}})
        for item in audios:
            content.append({
                "type": "text",
                "text": (
                    f"Analysis artifact for <Audio {item['index']}>: time-frequency spectrogram. "
                    "Use it only for timing, rhythm, energy, silence, and dynamics; it is not a source picture."
                ),
            })
            content.append({"type": "image_url", "image_url": {"url": item["spectrogram_uri"]}})
            if item.get("raw_wav_base64"):
                content.append({
                    "type": "input_audio",
                    "input_audio": {"data": item["raw_wav_base64"], "format": "wav"},
                })
        return content

    def run(self, client, model_id, backend_label, kwargs):
        result = {}
        resolved_mode = ""
        try:
            if not (kwargs.get("🔗 外部文本输入") or kwargs.get("📝 原始视频需求") or "").strip():
                raise ValueError("原始视频需求不能为空。")

            ordered_images = self._collect_images(kwargs)
            videos, audios = self._collect_video_audio(kwargs)
            self._validate_source_limits(ordered_images, videos, audios)
            # 外部专用提示词框的素材标记始终优先；只有未连接外部标记时，
            # 才使用本节点根据下游官方H3节点自动维护的清单。
            reference_manifest = parse_reference_manifest(
                kwargs.get("🧩 H3素材标记") or kwargs.get("🧩 H3自动素材清单")
            )
            has_first = kwargs.get("🎬 首帧图") is not None
            has_last = kwargs.get("🏁 尾帧图") is not None
            has_references = any(kwargs.get(f"🖼️ 参考图{index}") is not None for index in range(1, MAX_H3_IMAGES + 1))
            has_video_or_audio = bool(videos or audios)
            if reference_manifest:
                resolved_mode = reference_manifest["mode"]
                selected_mode = kwargs.get("🎛️ H3生成模式", "自动识别")
                if selected_mode != "自动识别":
                    selected_resolved_mode = self._resolve_mode(selected_mode, False, False, False, False)
                    if selected_resolved_mode != resolved_mode:
                        raise ValueError(
                            f"H3生成模式选择了{selected_resolved_mode}，但下游官方H3节点实际是{resolved_mode}。"
                        )
                counts = reference_manifest["counts"]
                if resolved_mode == "Ref2VA" and not (counts["Picture"] or counts["Video"]):
                    raise ValueError("下游MiniMax H3 Reference to Video尚未连接图片或视频参考素材。")
                actual_counts = {"Picture": len(ordered_images), "Video": len(videos), "Audio": len(audios)}
                for kind, actual_count in actual_counts.items():
                    if actual_count > counts[kind]:
                        raise ValueError(
                            f"H3提示词节点接入了{actual_count}个{kind}分析素材，"
                            f"但下游官方节点只有{counts[kind]}个对应素材，编号会错位。"
                        )
                if resolved_mode != "Ref2VA" and any(actual_counts.values()):
                    self._validate_mode(resolved_mode, has_first, has_last, has_references, has_video_or_audio)
                image_count = counts["Picture"]
                video_count = counts["Video"]
                audio_count = counts["Audio"]
            else:
                resolved_mode = self._resolve_mode(
                    kwargs.get("🎛️ H3生成模式", "自动识别"), has_first, has_last, has_references, has_video_or_audio
                )
                self._validate_mode(resolved_mode, has_first, has_last, has_references, has_video_or_audio)
                image_count = len(ordered_images)
                video_count = len(videos)
                audio_count = len(audios)

            output_chinese = bool(kwargs.get("🌐 输出中文提示词", False))
            messages = [
                {
                    "role": "system",
                    "content": h3_spec.SYSTEM_PROMPT + "\n\n" + (
                        h3_spec.LANGUAGE_POLICY_CHINESE if output_chinese else h3_spec.LANGUAGE_POLICY_ENGLISH
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_user_content(
                        kwargs, resolved_mode, kwargs.get("🎨 创作类型", "通用H3"),
                        ordered_images, videos, audios, reference_manifest
                    ),
                },
            ]
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": float(kwargs.get("🌡️ 温度", 0.4)),
                "max_tokens": int(kwargs.get("📝 最大输出令牌", 4096)),
                "top_p": float(kwargs.get("🎲 Top_P", 1.0)),
                "seed": int(kwargs.get("🎲 随机种", 0) or 0) % 0xFFFFFFFF,
                "stream": False,
            }
            safe_print(
                f"[AlexH3] 提交编译：backend={backend_label}，model={model_id}，H3模式={resolved_mode}，"
                f"创作类型={kwargs.get('🎨 创作类型', '通用H3')}，"
                f"输出语言={'中文' if output_chinese else '英文'}，"
                f"图片={len(ordered_images)}，视频={len(videos)}，音频={len(audios)}"
            )
            started = time.time()
            result = client.chat(payload)
            raw_text = extract_text(result)
            if not raw_text:
                raise RuntimeError("LLM返回内容为空。")
            compiled = parse_h3_compiler_output(raw_text, resolved_mode)
            h3_prompt, blank_removed = collapse_blank_runs(compiled["h3_prompt"])
            if not h3_prompt:
                raise RuntimeError("LLM没有返回H3提示词。")
            returned_mode = resolved_mode
            analysis = compiled["material_analysis"]
            if compiled["mode"] and compiled["mode"] != resolved_mode:
                analysis = (
                    analysis
                    + f"\n\n结构校验：LLM返回mode={compiled['mode']}，节点已按实际素材锁定为{resolved_mode}。"
                ).strip()
            if compiled["production_notes"]:
                analysis = (analysis + "\n\n制作说明：\n" + compiled["production_notes"]).strip()

            reference_issues = audit_reference_manifest(h3_prompt, reference_manifest)
            if reference_issues:
                raise RuntimeError(
                    "LLM改动了官方H3素材编号，为避免素材错位已停止输出：" + "；".join(reference_issues)
                )

            audit_issues = audit_h3_prompt(
                h3_prompt, resolved_mode,
                int(kwargs.get("⏱️ 目标时长(秒)", 5)),
                image_count, video_count, audio_count,
            )
            if audit_issues:
                analysis = (analysis + "\n\n结构校验提醒：\n- " + "\n- ".join(audit_issues)).strip()

            finish_reason = extract_finish_reason(result)
            quality_warnings = []
            if finish_reason == "length":
                quality_warnings.append(
                    "输出被最大输出令牌截断（finish_reason=length）：请提高📝最大输出令牌，"
                    "或降低图像最大token/参考图数量以缩短输入。"
                )
            if blank_removed > 1500:
                quality_warnings.append(
                    f"检测到约{blank_removed}字符的重复空行（复读循环），已自动压缩；"
                    "如反复出现请把🔁重复惩罚提高到1.2–1.3，或更换指令遵循更强的更大模型。"
                )
            if quality_warnings:
                analysis = (analysis + "\n\n⚠️ 输出质量提醒：\n- " + "\n- ".join(quality_warnings)).strip()

            usage = result.get("usage", {}) if isinstance(result, dict) else {}
            info = (
                "✅ H3视频提示词生成完成\n"
                f"🖥️ 推理后端：{backend_label}\n"
                f"🤖 模型：{model_id}\n"
                f"🎛️ H3模式：{returned_mode}\n"
                f"🎨 创作类型：{kwargs.get('🎨 创作类型', '通用H3')}\n"
                f"🌐 提示词语言：{'简体中文' if output_chinese else '英文'}\n"
                f"⏱️ 时长：{int(kwargs.get('⏱️ 目标时长(秒)', 5))}秒\n"
                f"📐 比例：{kwargs.get('📐 视频比例', '16:9')}\n"
                f"🔗 官方素材编号：{'已锁定' if reference_manifest else '按本节点输入生成'}\n"
                f"🖼️ 参考图：{image_count}张（LLM实际分析{len(ordered_images)}张）\n"
                f"🎞️ 参考视频：{video_count}个（LLM实际分析{len(videos)}个 / {sum(item['duration'] for item in videos):.2f}秒）\n"
                f"🎵 参考音频：{audio_count}个（LLM实际分析{len(audios)}个 / {sum(item['duration'] for item in audios):.2f}秒）\n"
                f"🔎 结构校验：{'通过' if not audit_issues else f'发现{len(audit_issues)}项提醒'}\n"
                f"📥 输入令牌：{usage.get('prompt_tokens', usage.get('input_tokens', '未知'))}\n"
                f"📤 输出令牌：{usage.get('completion_tokens', usage.get('output_tokens', '未知'))}\n"
                f"⏱️ 耗时：{time.time() - started:.2f}秒"
            )
            return (h3_prompt, returned_mode, analysis,
                    json.dumps(sanitized_result(result), ensure_ascii=False, indent=2), info)
        except Exception as error:
            message = f"❌ H3视频提示词生成失败：{error}"
            safe_print(message)
            safe_print(traceback.format_exc())
            response_text = json.dumps({"error": str(error), "response": sanitized_result(result)},
                                       ensure_ascii=False, indent=2)
            if kwargs.get("🚫 出错时跳过", False):
                return message, resolved_mode or "未知", message, response_text, message
            raise RuntimeError(message) from error


ENGINE = H3CompilerEngine()


class AlexH3PromptLocal:
    """alex_h3_prompt_local — H3 Context-IR compiler on local GGUF models."""

    @classmethod
    def INPUT_TYPES(cls):
        schema = business_inputs()
        schema["required"] = {**local_model_inputs(), **schema["required"]}
        return schema

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("🎬 H3最终提示词", "🎛️ 识别模式", "📑 素材与制作分析", "📄 LLM完整响应", "ℹ️ 处理信息")
    FUNCTION = "generate_prompt"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("本地GGUF编译MiniMax H3 Context-IR提示词：T2VA/I2VA/FL2VA/L2VA与9图+3视频帧批次+3音频Ref2VA，"
                   "31种创作预设、官方素材编号锁定与结构审计；输出直连官方MiniMax H3节点。")

    async def generate_prompt(self, **kwargs):
        settings = local_settings_from_kwargs(kwargs)
        return await asyncio.to_thread(
            ENGINE.run, LocalLLMClient(settings), f"local-llama-cpp（{settings['model_file']}）",
            "本地 llama.cpp (GGUF)", kwargs,
        )


class AlexH3PromptAPI:
    """alex_h3_prompt_API — H3 Context-IR compiler on an OpenAI-compatible endpoint."""

    @classmethod
    def INPUT_TYPES(cls):
        schema = business_inputs()
        schema["required"] = {**api_model_inputs(), **schema["required"]}
        return schema

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("🎬 H3最终提示词", "🎛️ 识别模式", "📑 素材与制作分析", "📄 LLM完整响应", "ℹ️ 处理信息")
    FUNCTION = "generate_prompt"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("OpenAI兼容端点编译MiniMax H3 Context-IR提示词：T2VA/I2VA/FL2VA/L2VA与9图+3视频帧批次+3音频Ref2VA，"
                   "31种创作预设、官方素材编号锁定与结构审计；模型列表可刷新。")

    async def generate_prompt(self, **kwargs):
        client = api_client_from_kwargs(kwargs)
        model_id = api_model_from_kwargs(kwargs)
        endpoint = client.endpoint
        return await asyncio.to_thread(ENGINE.run, client, model_id, endpoint, kwargs)


# ------------------------------------------------------------
# H3 dedicated prompt box (no LLM; validates official asset labels)
# ------------------------------------------------------------

REFERENCE_TYPE = "DAPAO_H3_REFERENCES"


class AlexH3PromptBox:
    """alex_h3_prompt_box — hand-written H3 prompt editor with stable reference metadata."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "📝 H3提示词": ("STRING", {
                    "multiline": True, "dynamicPrompts": True, "default": "",
                    "placeholder": "输入提示词；键入 @ 选择官方H3节点已连接的素材……",
                }),
                "🧩 H3素材清单": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "由节点界面根据下游官方MiniMax H3节点自动维护。",
                }),
            }
        }

    RETURN_TYPES = ("STRING", REFERENCE_TYPE)
    RETURN_NAMES = ("📝 H3提示词", "🧩 H3素材标记")
    FUNCTION = "build_prompt"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = "为MiniMax H3编写带官方<Picture/Video/Audio N>素材标记的提示词；素材清单由前端根据下游官方H3节点自动维护。"

    def build_prompt(self, **kwargs):
        text = str(kwargs.get("📝 H3提示词") or "").strip()
        manifest = parse_reference_manifest(kwargs.get("🧩 H3素材清单"))
        if manifest is None:
            manifest = {"version": 1, "mode": "T2VA", "target": "", "items": []}
        token_pattern = re.compile(r"<(Picture|Video|Audio)\s+(\d+)>")
        reference_like = re.compile(r"<\s*(?:Picture|Video|Audio)[^>]*>", re.IGNORECASE)
        allowed = {item["token"] for item in manifest["items"]}
        used = {match.group(0) for match in token_pattern.finditer(text)}
        malformed = sorted(set(reference_like.findall(text)) - used)
        if malformed:
            raise ValueError(
                "H3素材标记格式不正确，请使用<Picture 1>、<Video 1>、<Audio 1>格式："
                + "、".join(malformed)
            )
        unknown = sorted(used - allowed)
        if unknown:
            raise ValueError("提示词引用了当前官方H3节点未连接的素材：" + "、".join(unknown))
        return text, manifest


NODE_CLASS_MAPPINGS = {
    "alex_h3_prompt_local": AlexH3PromptLocal,
    "alex_h3_prompt_API": AlexH3PromptAPI,
    "alex_h3_prompt_box": AlexH3PromptBox,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "alex_h3_prompt_local": "alex_h3_prompt_local｜H3视频提示词(本地GGUF)",
    "alex_h3_prompt_API": "alex_h3_prompt_API｜H3视频提示词(OpenAI兼容)",
    "alex_h3_prompt_box": "alex_h3_prompt_box｜H3专用提示词框",
}
