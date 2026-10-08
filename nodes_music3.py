"""MiniMax Music 3 structured-caption + lyrics compiler nodes.

Core value ported from ComfyUI-llama_Dapao: a generation-ready three-part
Music 3 caption (Global Metadata / Vocal Details / Arrangement) plus complete
lyrics, backed by a bundled local style library (genre router, per-family
index cards, 1000 caption templates). The first two outputs connect directly
to the official Music3 Text Encode node. Lyrics are never leaked into the
caption; instrumental requests are enforced.

Two backends share one engine:
  * alex_music3_local — local GGUF via llama-cpp-python
  * alex_music3_API   — OpenAI-compatible endpoint
"""

import asyncio
import json
import re
import time
import traceback

from .alex_minimax import music3_spec
from .alex_minimax.llm_common import safe_print, extract_text, sanitized_result
from .alex_minimax.backend_local import local_model_inputs, local_settings_from_kwargs, LocalLLMClient
from .alex_minimax.backend_api import api_model_inputs, api_client_from_kwargs, api_model_from_kwargs

NODE_CATEGORY = "Alex/MiniMax/Music3"


def business_inputs():
    """INPUT_TYPES fragment shared by both Music3 nodes."""
    return {
        "required": {
            "📝 原始音乐需求": ("STRING", {
                "multiline": True,
                "default": "温暖的原声流行歌曲，亲密女声，副歌逐步扩张并在结尾温柔收束。",
                "placeholder": "描述音乐风格、情绪、场景或你希望保留的核心元素……",
            }),
            "🎼 主风格": (music3_spec.GENRE_FAMILIES, {"default": "自动识别"}),
            "🧬 融合风格": (["无"] + music3_spec.GENRE_FAMILIES, {"default": "无"}),
            "🎯 使用场景": (music3_spec.SCENARIO_OPTIONS, {"default": "自动识别"}),
            "⏳ 目标曲长": (music3_spec.DURATION_OPTIONS, {"default": "自动识别"}),
            "💫 情绪弧": (music3_spec.MOOD_ARCS, {"default": "自动识别"}),
            "⏱️ 速度": (music3_spec.TEMPO_OPTIONS, {"default": "自动识别"}),
            "🎹 调性倾向": (music3_spec.TONALITY_OPTIONS, {"default": "自动识别/不指定"}),
            "🎚️ 拍号/律动": (music3_spec.METER_OPTIONS, {"default": "自动识别"}),
            "🥁 核心律动": (music3_spec.GROOVE_OPTIONS, {"default": "自动识别"}),
            "🎙️ 人声配置": (music3_spec.VOCAL_OPTIONS, {"default": "自动识别"}),
            "📈 人声音域": (music3_spec.REGISTER_OPTIONS, {"default": "自动识别"}),
            "🗣️ 人声音色": (music3_spec.TIMBRE_OPTIONS, {"default": "自动识别"}),
            "🎤 演唱方式": (music3_spec.DELIVERY_OPTIONS, {"default": "自动识别"}),
            "👥 和声/伴唱": (music3_spec.HARMONY_OPTIONS, {"default": "自动识别"}),
            "🎻 核心乐器编制": (music3_spec.INSTRUMENT_OPTIONS, {"default": "自动识别"}),
            "🧱 歌曲结构": (music3_spec.STRUCTURE_OPTIONS, {"default": "自动识别"}),
            "🎛️ 制作质感": (music3_spec.PRODUCTION_OPTIONS, {"default": "自动识别"}),
            "🌌 空间与混响": (music3_spec.SPACE_OPTIONS, {"default": "自动识别"}),
            "🔥 编曲密度": (music3_spec.DENSITY_OPTIONS, {"default": "自动识别"}),
            "🚫 排除项": (music3_spec.EXCLUSION_OPTIONS, {"default": "无"}),
            "🌐 输出语言": (music3_spec.LANGUAGE_OPTIONS, {"default": "英文（Music 3推荐）"}),
            "📏 输出详略": (music3_spec.DETAIL_OPTIONS, {"default": "标准｜250–450词"}),
            "🌡️ 温度": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 2.0, "step": 0.01}),
            "📝 最大输出令牌": ("INT", {"default": 4096, "min": 512, "max": 16384, "step": 1}),
            "🎲 Top_P": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "🎲 随机种": ("INT", {
                "default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                "control_after_generate": "randomize",
                "tooltip": "本地后端会作为llama.cpp采样种子；API后端仅控制ComfyUI缓存。",
            }),
        },
        "optional": {
            "🔗 外部音乐需求": ("STRING", {"forceInput": True, "default": "", "tooltip": "连接任意STRING节点；存在时与本节点的原始音乐需求合并。"}),
            "📝 歌词": ("STRING", {
                "multiline": True, "default": "",
                "placeholder": "可选。留空时自动生成完整歌词；填写后原样输出，可含 [Verse]、[Chorus]、[Bridge] 等段落标签。",
            }),
            "🔗 外部歌词": ("STRING", {"forceInput": True, "default": "", "tooltip": "可连接歌词文本；存在时与本节点歌词合并并原样输出。没有任何歌词输入时由LLM自动生成。"}),
            "➕ 补充约束": ("STRING", {"multiline": True, "default": "", "placeholder": "可选：指定BPM、调性、必须保留的乐器、时长、用途或额外禁用项。"}),
            "✍️ 自定义主风格": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义融合风格": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义使用场景": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义目标曲长": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义情绪弧": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义速度": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义调性倾向": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义拍号/律动": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义核心律动": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义人声配置": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义人声音域": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义人声音色": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义演唱方式": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义和声/伴唱": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义乐器编制": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义歌曲结构": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义制作质感": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义空间与混响": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义编曲密度": ("STRING", {"multiline": True, "default": ""}),
            "✍️ 自定义输出详略": ("STRING", {"multiline": True, "default": "", "placeholder": "例如：320–400 English words"}),
            "🚫 出错时跳过": ("BOOLEAN", {"default": False}),
        },
    }


class Music3Engine:
    """All business logic; the backend is injected as a client with .chat(payload)."""

    @staticmethod
    def _compose_controls(kwargs):
        fields = [
            ("主风格", "🎼 主风格", "✍️ 自定义主风格"),
            ("融合风格", "🧬 融合风格", "✍️ 自定义融合风格"),
            ("使用场景", "🎯 使用场景", "✍️ 自定义使用场景"),
            ("目标曲长", "⏳ 目标曲长", "✍️ 自定义目标曲长"),
            ("情绪弧", "💫 情绪弧", "✍️ 自定义情绪弧"),
            ("速度", "⏱️ 速度", "✍️ 自定义速度"),
            ("调性倾向", "🎹 调性倾向", "✍️ 自定义调性倾向"),
            ("拍号/律动", "🎚️ 拍号/律动", "✍️ 自定义拍号/律动"),
            ("核心律动", "🥁 核心律动", "✍️ 自定义核心律动"),
            ("人声配置", "🎙️ 人声配置", "✍️ 自定义人声配置"),
            ("人声音域", "📈 人声音域", "✍️ 自定义人声音域"),
            ("人声音色", "🗣️ 人声音色", "✍️ 自定义人声音色"),
            ("演唱方式", "🎤 演唱方式", "✍️ 自定义演唱方式"),
            ("和声/伴唱", "👥 和声/伴唱", "✍️ 自定义和声/伴唱"),
            ("核心乐器编制", "🎻 核心乐器编制", "✍️ 自定义乐器编制"),
            ("歌曲结构", "🧱 歌曲结构", "✍️ 自定义歌曲结构"),
            ("制作质感", "🎛️ 制作质感", "✍️ 自定义制作质感"),
            ("空间与混响", "🌌 空间与混响", "✍️ 自定义空间与混响"),
            ("编曲密度", "🔥 编曲密度", "✍️ 自定义编曲密度"),
            ("排除项", "🚫 排除项", "✍️ 自定义排除项"),
            ("输出详略", "📏 输出详略", "✍️ 自定义输出详略"),
        ]
        controls = {}
        for label, field, custom_field in fields:
            value = kwargs.get(field, "自动识别")
            if label == "融合风格" and value == "无":
                controls[label] = "无"
            elif label == "排除项" and value == "无":
                controls[label] = "无"
            else:
                controls[label] = music3_spec.choice_with_custom(value, kwargs.get(custom_field, ""))
        return controls

    @staticmethod
    def _reference_families(kwargs):
        main = kwargs.get("🎼 主风格", "自动识别")
        fusion = kwargs.get("🧬 融合风格", "无")
        routing_text = "\n".join(
            str(kwargs.get(name) or "")
            for name in ("📝 原始音乐需求", "🔗 外部音乐需求", "➕ 补充约束")
        )
        primary = music3_spec.FAMILY_FILE_BY_OPTION.get(main)
        if main == "自动识别":
            primary = music3_spec.route_automatic_family(routing_text)
        families = [primary]
        if fusion == "自动识别" and re.search(r"(?:融合|混合|结合|with|influence|/|\+)", routing_text, re.I):
            families.append(music3_spec.route_automatic_family(routing_text, exclude=primary))
        elif fusion != "无":
            families.append(music3_spec.FAMILY_FILE_BY_OPTION.get(fusion))
        return [family for family in families if family]

    @staticmethod
    def _build_user_content(request, lyrics, controls, output_language, references):
        tags = music3_spec.extract_lyric_tags(lyrics)
        reference_blocks = []
        for number, reference in enumerate(references, 1):
            card = reference["card"]
            reference_blocks.append(
                f"REFERENCE {number} (internal inspiration only, do not copy):\n"
                f"Role candidate: style={card['style']}; tempo/key={card['tempo']}; mood={card['mood']}; "
                f"vocal={card['vocal']}; palette={card['palette']}\n"
                f"Complete reference caption:\n{reference['caption']}"
            )
        language_instruction = {
            "英文（Music 3推荐）": "Write all caption content in English.",
            "中文": "Write all caption content in Simplified Chinese. Keep the three final heading names in English when the caller assembles them.",
            "双语：英文为主、中文注释": "Write the main caption content in English, then add concise Simplified Chinese explanations in parentheses only where useful.",
        }.get(output_language, "Write all caption content in English.")
        instrumental = music3_spec.is_instrumental_request(request, controls)
        if lyrics.strip():
            lyrics_mode = "SOURCE LYRICS PROVIDED: preserve them externally; generated_lyrics must be empty."
        elif instrumental:
            lyrics_mode = "INSTRUMENTAL REQUEST: generated_lyrics must be empty."
        else:
            lyrics_mode = "NO SOURCE LYRICS: generate a complete original, section-tagged lyric in generated_lyrics."
        references_text = "\n\n".join(reference_blocks) if reference_blocks else \
            "No precise family was selected. Use conservative general-pop routing from the explicit controls."
        return (
            "USER MUSIC REQUEST:\n"
            f"{request}\n\n"
            "EXPLICIT CONTROL PANEL:\n"
            f"{json.dumps(controls, ensure_ascii=False, indent=2)}\n\n"
            f"LYRIC SECTION TAGS ONLY (must be honored as local arrangement directives): {', '.join(tags) if tags else 'none'}\n"
            f"LYRICS MODE: {lyrics_mode}\n"
            "SOURCE LYRICS FOR PRIVATE HIGH-LEVEL MOOD ANALYSIS ONLY. Never quote, paraphrase, summarize, translate, or repeat them in the caption:\n"
            f"{lyrics if lyrics.strip() else '[no lyrics supplied]'}\n\n"
            f"OUTPUT LANGUAGE: {language_instruction}\n"
            "Always return the required JSON object; the node will assemble the Music 3 caption and choose source or generated lyrics separately.\n\n"
            "SELECTED LOCAL STYLE REFERENCES:\n"
            f"{references_text}"
        )

    def run(self, client, model_id, backend_label, kwargs):
        result = {}
        try:
            request_parts = [str(kwargs.get("📝 原始音乐需求") or "").strip(), str(kwargs.get("🔗 外部音乐需求") or "").strip()]
            request = "\n\n".join(part for part in request_parts if part)
            if not request:
                raise ValueError("原始音乐需求不能为空。")
            lyric_parts = [str(kwargs.get("📝 歌词") or "").strip(), str(kwargs.get("🔗 外部歌词") or "").strip()]
            lyrics = "\n".join(part for part in lyric_parts if part)
            supplement = str(kwargs.get("➕ 补充约束") or "").strip()
            if supplement:
                request = f"{request}\n\nAdditional explicit constraints:\n{supplement}"
            controls = self._compose_controls(kwargs)
            output_language = kwargs.get("🌐 输出语言", "英文（Music 3推荐）")
            if output_language not in music3_spec.LANGUAGE_OPTIONS:
                raise ValueError("输出语言不受支持。")
            reference_families = self._reference_families(kwargs)
            reference_query = " ".join([request, *controls.values()])
            references = music3_spec.select_templates(reference_families, reference_query)
            user_content = self._build_user_content(request, lyrics, controls, output_language, references)
            payload = {
                "model": model_id,
                "messages": [{"role": "system", "content": music3_spec.SYSTEM_PROMPT},
                             {"role": "user", "content": user_content}],
                "temperature": float(kwargs.get("🌡️ 温度", 0.35)),
                "max_tokens": int(kwargs.get("📝 最大输出令牌", 4096)),
                "top_p": float(kwargs.get("🎲 Top_P", 1.0)),
                "seed": int(kwargs.get("🎲 随机种", 0) or 0) % 0xFFFFFFFF,
                "stream": False,
            }
            safe_print(f"[AlexMusic3] 提交编译：backend={backend_label}，model={model_id}，"
                       f"参考族={reference_families or ['自动路由']}，模板={len(references)}")
            started = time.time()
            result = client.chat(payload)
            raw_text = extract_text(result)
            if not raw_text:
                raise RuntimeError("LLM返回内容为空。")
            compiled = music3_spec.parse_music3_output(raw_text)
            if not all((compiled["global_metadata"], compiled["vocal_details"], compiled["arrangement"])):
                raise RuntimeError("LLM未按Music 3规范返回完整的Global Metadata、Vocal Details和Arrangement。")
            caption = compiled["caption"]
            leakage = music3_spec.lyric_leakage(lyrics, caption)
            if leakage:
                raise RuntimeError("LLM错误复述了歌词正文，为避免把歌词写入Music Caption已停止输出。")
            instrumental_requested = music3_spec.is_instrumental_request(request, controls)
            instrumental_text = compiled["vocal_details"]
            affirmative_vocals = re.search(r"\b(?:singer|vocalist|lead vocals?|backing vocals?|singing|sung)\b", instrumental_text, re.I)
            negated_vocals = re.search(r"\b(?:no|without|absent|contains no)\s+(?:lead |backing )?vocals?\b|纯器乐|无人声|不含人声", instrumental_text, re.I)
            if instrumental_requested and affirmative_vocals and not negated_vocals:
                raise RuntimeError("LLM未遵守“纯器乐”要求，Vocal Details中仍出现人声内容。")
            if lyrics:
                output_lyrics = lyrics
                lyrics_mode = "保留用户输入歌词"
            elif instrumental_requested:
                output_lyrics = ""
                lyrics_mode = "纯器乐（无需歌词）"
            else:
                output_lyrics = music3_spec.validate_generated_lyrics(compiled["generated_lyrics"])
                lyrics_mode = "LLM自动生成完整歌词"
            usage = result.get("usage", {}) if isinstance(result, dict) else {}
            analysis = (
                "✅ Music 3结构化Caption已生成\n"
                f"主风格：{controls['主风格']}\n"
                f"融合风格：{controls['融合风格']}\n"
                f"本地参考：{len(references)}条（仅用于内部风格与编曲参考）\n"
                f"歌词段落标签：{', '.join(music3_spec.extract_lyric_tags(output_lyrics)) if output_lyrics else '纯器乐，无歌词'}\n"
                f"歌词处理：{lyrics_mode}\n"
                f"约束校验：{compiled['validation'] or '已检查三段结构、显式控制与歌词正文隔离。'}"
            )
            info = (
                "✅ Music3音乐提示词生成完成\n"
                f"🖥️ 推理后端：{backend_label}\n"
                f"🤖 模型：{model_id}\n"
                f"🎼 主风格：{controls['主风格']}\n"
                f"🧬 融合风格：{controls['融合风格']}\n"
                f"📚 本地参考模板：{len(references)}条\n"
                "📦 输出内容：Music3结构化音乐描述 + 完整歌词\n"
                f"📝 歌词处理：{lyrics_mode}\n"
                f"📥 输入令牌：{usage.get('prompt_tokens', usage.get('input_tokens', '未知'))}\n"
                f"📤 输出令牌：{usage.get('completion_tokens', usage.get('output_tokens', '未知'))}\n"
                f"⏱️ 耗时：{time.time() - started:.2f}秒"
            )
            return (caption, output_lyrics, compiled["global_metadata"], compiled["vocal_details"],
                    compiled["arrangement"], analysis,
                    json.dumps(sanitized_result(result), ensure_ascii=False, indent=2), info)
        except Exception as error:
            message = f"❌ Music3音乐提示词生成失败：{error}"
            safe_print(message)
            safe_print(traceback.format_exc())
            response_text = json.dumps({"error": str(error), "response": sanitized_result(result)},
                                       ensure_ascii=False, indent=2)
            if kwargs.get("🚫 出错时跳过", False):
                return (message, str(kwargs.get("🔗 外部歌词") or kwargs.get("📝 歌词") or ""),
                        message, message, message, message, response_text, message)
            raise RuntimeError(message) from error


ENGINE = Music3Engine()


class AlexMusic3Local:
    """alex_music3_local — MiniMax Music 3 caption compiler on local GGUF models."""

    @classmethod
    def INPUT_TYPES(cls):
        schema = business_inputs()
        schema["required"] = {**local_model_inputs(), **schema["required"]}
        return schema

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("🎼 音乐描述", "📝 歌词", "🌐 全局音乐信息", "🎙️ 人声细节", "🧱 编曲结构",
                    "📑 音乐结构分析", "📄 语言模型完整响应", "ℹ️ 处理信息")
    FUNCTION = "generate_prompt"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("本地GGUF生成MiniMax Music 3结构化音乐描述和完整歌词；无歌词时自动创作，有歌词时原样保留，"
                   "前两个输出可直连官方Music3 Text Encode；内置1000条本地风格模板。")

    async def generate_prompt(self, **kwargs):
        settings = local_settings_from_kwargs(kwargs)
        return await asyncio.to_thread(
            ENGINE.run, LocalLLMClient(settings), f"local-llama-cpp（{settings['model_file']}）",
            "本地 llama.cpp (GGUF)", kwargs,
        )


class AlexMusic3API:
    """alex_music3_API — MiniMax Music 3 caption compiler on an OpenAI-compatible endpoint."""

    @classmethod
    def INPUT_TYPES(cls):
        schema = business_inputs()
        schema["required"] = {**api_model_inputs(), **schema["required"]}
        return schema

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("🎼 音乐描述", "📝 歌词", "🌐 全局音乐信息", "🎙️ 人声细节", "🧱 编曲结构",
                    "📑 音乐结构分析", "📄 语言模型完整响应", "ℹ️ 处理信息")
    FUNCTION = "generate_prompt"
    CATEGORY = NODE_CATEGORY
    DESCRIPTION = ("OpenAI兼容端点生成MiniMax Music 3结构化音乐描述和完整歌词；无歌词时自动创作，有歌词时原样保留，"
                   "前两个输出可直连官方Music3 Text Encode；内置1000条本地风格模板。")

    async def generate_prompt(self, **kwargs):
        client = api_client_from_kwargs(kwargs)
        model_id = api_model_from_kwargs(kwargs)
        endpoint = client.endpoint
        return await asyncio.to_thread(ENGINE.run, client, model_id, endpoint, kwargs)


NODE_CLASS_MAPPINGS = {
    "alex_music3_local": AlexMusic3Local,
    "alex_music3_API": AlexMusic3API,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "alex_music3_local": "alex_music3_local｜Music3音乐提示词(本地GGUF)",
    "alex_music3_API": "alex_music3_API｜Music3音乐提示词(OpenAI兼容)",
}
