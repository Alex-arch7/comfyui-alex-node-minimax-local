"""Skill-router MiniMax H3 prompt nodes (official MiniMax-H3 skill library).

The second H3 implementation ported from ComfyUI-llama_Dapao's
`本地H3提示词` (chflame163/ComfyUI_Qwen_H3_Prompt lineage): instead of the
flagship node's 31 built-in creative profiles, the prompt is driven by the
official MiniMax-H3 SKILL.md files (1 prompt-writing + 8 style generators,
plus user skills in resources/custom_skills). Up to three lightweight LLM
passes run per execution:

  1. deterministic mode detection from asset counts;
  2. an LLM mode router only when 1-2 pictures make the intent ambiguous
     (first frame vs last frame vs general reference);
  3. an LLM Skill router when Skill=auto.

Output format follows the selected Skill's own instructions (deliberately
loose contract); the node only guards against empty output and
retries once.

Backends: alex_h3_skill_local (local GGUF) / alex_h3_skill_API (OpenAI-compatible).
"""

import asyncio
import json
import time
import traceback

from .alex_minimax import h3_skill_spec
from .alex_minimax import media
from .alex_minimax.llm_common import safe_print, extract_text, sanitized_result
from .alex_minimax.backend_local import local_model_inputs, local_settings_from_kwargs, LocalLLMClient
from .alex_minimax.backend_api import api_model_inputs, api_client_from_kwargs, api_model_from_kwargs

NODE_CATEGORY = "Alex/MiniMax/H3"

SKILL_OPTIONS = ["auto", *h3_skill_spec.SKILL_NAMES]
REFERENCE_VIDEO_FPS_DEFAULT = 24.0


def business_inputs():
    """INPUT_TYPES fragment shared by both Skill-router nodes."""
    optional = {f"🖼️ 参考图{index}": ("IMAGE", {
        "tooltip": "每个接口一张图；首帧/尾帧/通用参考的用途写在需求描述里。最多9张。",
    }) for index in range(1, 10)}
    optional.update({f"🎞️ 参考视频{index}": ("IMAGE", {
        "tooltip": "连接IMAGE帧批次（视频读取节点帧率与「🎬参考视频帧率」一致）；按秒拼成contact sheet送模型。最多3个。",
    }) for index in range(1, 4)})
    optional["🚫 出错时跳过"] = ("BOOLEAN", {"default": False})
    return {
        "required": {
            "✏️ 需求描述": ("STRING", {
                "multiline": True, "default": "",
                "placeholder": "描述视频创意、素材用途、时长与风格；首帧/尾帧用途写清楚……",
            }),
            "🧩 Skill": (SKILL_OPTIONS, {
                "default": "auto",
                "tooltip": "auto=由轻量LLM路由自动选择；官方MiniMax-H3技能库在 resources/h3_skills，自定义放 resources/custom_skills。",
            }),
            "⏱️ 目标秒数": ("FLOAT", {
                "default": 10.0, "min": 1.0, "max": 60.0, "step": 0.5,
                "tooltip": "Skill流程允许1–60秒；直连官方H3节点时请保持在官方支持的4–15秒内。",
            }),
            "🎬 参考视频帧率": ("FLOAT", {
                "default": REFERENCE_VIDEO_FPS_DEFAULT, "min": 1.0, "max": 120.0, "step": 0.5,
                "tooltip": "参考视频IMAGE帧批次按该帧率解释时长。",
            }),
            "🎞️ 视频每秒采样帧数": ("INT", {"default": 2, "min": 1, "max": 8}),
            "🌡️ 温度": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.01}),
            "📝 最大输出令牌": ("INT", {"default": 8192, "min": 256, "max": 32768, "step": 128}),
            "🎲 随机种": ("INT", {
                "default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF, "control_after_generate": "randomize",
                "tooltip": "本地后端会作为llama.cpp采样种子；API后端仅控制ComfyUI缓存。",
            }),
        },
        "optional": optional,
    }


def _picture_role(mode, picture_index):
    if mode == "i2va":
        return "the target video's first frame"
    if mode == "l2va":
        return "the target video's last frame"
    if mode == "fl2va":
        return "the target video's first frame" if picture_index == 1 else "the target video's last frame"
    return "a general visual reference whose role follows the user request"


def _clean_reply(text):
    content = str(text or "")
    if "<think>" in content and "</think>" not in content:
        return ""
    if "</think>" in content:
        content = content.split("</think>", 1)[1]
    return content.strip()


class H3SkillEngine:
    """All business logic; the backend is injected as a client with .chat(payload)."""

    @staticmethod
    def _collect(kwargs):
        images = []
        for slot in range(1, 10):
            image = kwargs.get(f"🖼️ 参考图{slot}")
            if image is None:
                continue
            if image.shape[0] != 1:
                raise ValueError(f"参考图{slot}每个接口只能1张，当前批次{image.shape[0]}张；请先拆分。")
            images.append(image)
        fps = float(kwargs.get("🎬 参考视频帧率", REFERENCE_VIDEO_FPS_DEFAULT) or REFERENCE_VIDEO_FPS_DEFAULT)
        videos = []
        for slot in range(1, 4):
            frames = kwargs.get(f"🎞️ 参考视频{slot}")
            if frames is None:
                continue
            frame_count = int(frames.shape[0])
            if frame_count < 1:
                raise ValueError(f"参考视频{slot}至少需要1帧。")
            videos.append((frames, frame_count, frame_count / fps))
        return images, videos

    def run(self, client, model_id, backend_label, kwargs):
        started = time.time()
        result = {}
        try:
            prompt = str(kwargs.get("✏️ 需求描述") or "").strip()
            if not prompt:
                raise ValueError("请先填写需求描述。")
            skill_choice = kwargs.get("🧩 Skill", "auto")
            if skill_choice != "auto" and skill_choice not in h3_skill_spec.SKILL_NAMES:
                raise ValueError("所选Skill不存在，请重启ComfyUI或刷新Skill库后重新选择。")
            duration = float(kwargs.get("⏱️ 目标秒数", 10.0))
            sample_frames_per_second = int(kwargs.get("🎞️ 视频每秒采样帧数", 2) or 2)
            seed = int(kwargs.get("🎲 随机种", 0) or 0) % 0xFFFFFFFF
            fps = float(kwargs.get("🎬 参考视频帧率", REFERENCE_VIDEO_FPS_DEFAULT) or REFERENCE_VIDEO_FPS_DEFAULT)

            images, videos = self._collect(kwargs)

            mode = h3_skill_spec.detect_h3_mode(len(images), len(videos))
            mode_note = "按素材数量确定性判定"
            if mode is None:
                routing = client.chat({
                    "model": model_id,
                    "messages": h3_skill_spec.mode_router_prompt(prompt, len(images)),
                    "temperature": 0.0, "max_tokens": 32, "top_p": 1.0, "seed": seed, "stream": False,
                })
                mode = h3_skill_spec.parse_mode_selection(extract_text(routing), len(images))
                mode_note = "LLM路由判定（图片意图不明确）"

            content = [media.text_content(f"User request:\n{prompt}\n\nTarget duration: {duration:.2f} seconds.")]
            assets = []
            for picture_index, image in enumerate(images, 1):
                role = _picture_role(mode, picture_index)
                content.append(media.text_content(f"<Picture {picture_index}>: connected as {role}."))
                content.append(media.image_content(image))
                assets.append(f"Picture {picture_index}={role}")
            for video_index, (frames, frame_count, source_duration) in enumerate(videos, 1):
                groups = media.sample_indices_per_second(frame_count, fps, sample_frames_per_second)
                sampled = sum(len(indices) for indices in groups)
                content.append(media.text_content(
                    f"<Video {video_index}>: {frame_count} ordered frames at {fps:.3f} fps "
                    f"({source_duration:.2f} seconds), represented by {sampled} sampled frames "
                    f"grouped into {len(groups)} chronological one-second contact sheets."
                ))
                for second_index, indices in enumerate(groups):
                    timestamps = ", ".join(f"{frame_index / fps:.3f}s" for frame_index in indices)
                    content.append(media.text_content(
                        f"<Video {video_index}> second {second_index + 1}/{len(groups)} contact sheet. "
                        f"Read cells in row-major chronological order at: {timestamps}."
                    ))
                    content.append(media.image_grid_content(frames, indices))
                assets.append(f"Video {video_index}={source_duration:.2f}s/{sampled} sampled frames")
            asset_summary = ", ".join(assets) if assets else "none"

            selected = skill_choice
            skill_note = "手动指定"
            if selected == "auto":
                routing = client.chat({
                    "model": model_id,
                    "messages": h3_skill_spec.router_prompt(prompt, mode, asset_summary),
                    "temperature": 0.0, "max_tokens": 96, "top_p": 1.0, "seed": seed, "stream": False,
                })
                selected = h3_skill_spec.parse_skill_selection(extract_text(routing))
                skill_note = "LLM路由自动选择"

            messages = [
                {"role": "system", "content": h3_skill_spec.system_prompt(selected, mode, duration)},
                {"role": "user", "content": content},
            ]
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": float(kwargs.get("🌡️ 温度", 0.7)),
                "max_tokens": int(kwargs.get("📝 最大输出令牌", 8192)),
                "top_p": 1.0,
                "seed": seed,
                "stream": False,
            }
            safe_print(f"[AlexH3Skill] backend={backend_label} model={model_id} mode={mode} skill={selected} "
                       f"图片={len(images)} 视频={len(videos)}")
            response = client.chat(payload)
            output = _clean_reply(extract_text(response))
            issues = h3_skill_spec.output_issues(output, mode, duration)
            if issues:
                safe_print(f"[AlexH3Skill] 空输出，重试一次：{issues}")
                messages.extend([
                    {"role": "assistant", "content": output},
                    {"role": "user", "content": "Return the complete requested content only, following the selected Skill. Problems: " + "; ".join(issues)},
                ])
                response = client.chat(payload | {"messages": messages})
                output = _clean_reply(extract_text(response))
                if h3_skill_spec.output_issues(output, mode, duration):
                    raise RuntimeError("模型未返回正文。请提高上下文长度和最大输出令牌，或更换指令遵循更强的模型。")

            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            info = (
                "✅ Skill路由H3提示词生成完成\n"
                f"🖥️ 推理后端：{backend_label}\n"
                f"🤖 模型：{model_id}\n"
                f"🧭 识别模式：{mode.upper()}（{mode_note}）\n"
                f"🧩 选中Skill：{selected}（{skill_note}）\n"
                f"🖼️ 参考图：{len(images)}｜🎞️ 参考视频：{len(videos)}\n"
                f"⏱️ 目标秒数：{duration:.1f}\n"
                f"📥 输入令牌：{usage.get('prompt_tokens', usage.get('input_tokens', '未知'))}\n"
                f"📤 输出令牌：{usage.get('completion_tokens', usage.get('output_tokens', '未知'))}\n"
                f"⏱️ 耗时：{time.time() - started:.2f}秒"
            )
            return (output, selected, mode.upper(), info)
        except Exception as error:
            message = f"❌ Skill路由H3提示词生成失败：{error}"
            safe_print(message)
            safe_print(traceback.format_exc())
            response_text = json.dumps({"error": str(error), "response": sanitized_result(result)}, ensure_ascii=False, indent=2)
            if kwargs.get("🚫 出错时跳过", False):
                return message, str(kwargs.get("🧩 Skill") or ""), "未知", message
            raise RuntimeError(message) from error


ENGINE = H3SkillEngine()


class AlexH3SkillLocal:
    """alex_h3_skill_local — official MiniMax-H3 Skill library on local GGUF models."""

    @classmethod
    def INPUT_TYPES(cls):
        schema = business_inputs()
        schema["required"] = {**local_model_inputs(), **schema["required"]}
        return schema

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("🎬 H3提示词", "🧩 选中Skill", "🧭 识别模式", "ℹ️ 处理信息")
    FUNCTION = "generate_prompt"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("官方MiniMax-H3 Skill库驱动：模式判定(必要时LLM路由)+Skill自动路由+SKILL.md全文注入；"
                   "9图+3视频contact sheet；输出格式跟随所选Skill。本地GGUF推理。")

    async def generate_prompt(self, **kwargs):
        settings = local_settings_from_kwargs(kwargs)
        return await asyncio.to_thread(
            ENGINE.run, LocalLLMClient(settings), f"local-llama-cpp（{settings['model_file']}）",
            "本地 llama.cpp (GGUF)", kwargs,
        )


class AlexH3SkillAPI:
    """alex_h3_skill_API — official MiniMax-H3 Skill library on an OpenAI-compatible endpoint."""

    @classmethod
    def INPUT_TYPES(cls):
        schema = business_inputs()
        schema["required"] = {**api_model_inputs(), **schema["required"]}
        return schema

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("🎬 H3提示词", "🧩 选中Skill", "🧭 识别模式", "ℹ️ 处理信息")
    FUNCTION = "generate_prompt"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("官方MiniMax-H3 Skill库驱动：模式判定(必要时LLM路由)+Skill自动路由+SKILL.md全文注入；"
                   "9图+3视频contact sheet；输出格式跟随所选Skill。调用OpenAI兼容端点。")

    async def generate_prompt(self, **kwargs):
        client = api_client_from_kwargs(kwargs)
        model_id = api_model_from_kwargs(kwargs)
        endpoint = client.endpoint
        return await asyncio.to_thread(ENGINE.run, client, model_id, endpoint, kwargs)


NODE_CLASS_MAPPINGS = {
    "alex_h3_skill_local": AlexH3SkillLocal,
    "alex_h3_skill_API": AlexH3SkillAPI,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "alex_h3_skill_local": "alex_h3_skill_local｜H3提示词·Skill路由(本地GGUF)",
    "alex_h3_skill_API": "alex_h3_skill_API｜H3提示词·Skill路由(OpenAI兼容)",
}
