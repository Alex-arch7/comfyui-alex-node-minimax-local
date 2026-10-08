"""MiniMax Music 3 structured-caption spec: option panels, style-family routing,
local reference-library selection, and output parsing.

Adapted from ComfyUI-llama_Dapao (music3_caption_prompt_node.py). The bundled
style library lives in resources/music3_caption_rewriter (genre router,
per-family index cards and 1000 caption templates).
"""

import json
import re
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent.parent / "resources" / "music3_caption_rewriter"

GENRE_FAMILIES = [
    "自动识别",
    "东亚现代流行｜C-pop/J-pop与电子、R&B、说唱融合",
    "东亚抒情与国风｜华语/日系抒情、原声或管弦",
    "现代R&B与Neo-Soul",
    "灵魂、蓝调与福音",
    "电影感流行抒情",
    "电影管弦与史诗配乐",
    "电子、合成器与氛围流行",
    "爵士、摇摆与大乐队",
    "传统声乐、音乐剧与舞台",
    "嘻哈、说唱、Trap与Drill",
    "金属与重型摇滚",
    "流行、另类与独立摇滚",
    "当代民谣与原声",
    "根源、传统与世界音乐",
    "通用流行与抒情",
    "舞曲流行、迪斯科与Funk",
    "俱乐部EDM、House与Trance",
    "乡村与Americana",
    "自定义",
]

FAMILY_FILE_BY_OPTION = {
    "东亚现代流行｜C-pop/J-pop与电子、R&B、说唱融合": "east-asian-modern",
    "东亚抒情与国风｜华语/日系抒情、原声或管弦": "east-asian-ballad-heritage",
    "现代R&B与Neo-Soul": "modern-rnb-neo-soul",
    "灵魂、蓝调与福音": "soul-blues-gospel",
    "电影感流行抒情": "cinematic-pop-ballad",
    "电影管弦与史诗配乐": "cinematic-orchestral-epic",
    "电子、合成器与氛围流行": "electronic-synth-ambient-pop",
    "爵士、摇摆与大乐队": "jazz-swing-big-band",
    "传统声乐、音乐剧与舞台": "traditional-vocal-stage",
    "嘻哈、说唱、Trap与Drill": "hip-hop-rap",
    "金属与重型摇滚": "metal-heavy-rock",
    "流行、另类与独立摇滚": "pop-alternative-rock",
    "当代民谣与原声": "contemporary-folk-acoustic",
    "根源、传统与世界音乐": "roots-traditional-global",
    "通用流行与抒情": "general-pop-ballad",
    "舞曲流行、迪斯科与Funk": "dance-pop-disco-funk",
    "俱乐部EDM、House与Trance": "club-edm-house-trance",
    "乡村与Americana": "country-americana",
}

AUTO_ROUTE_CUES = {
    "east-asian-modern": ("c-pop", "mandopop", "cantopop", "j-pop", "华语流行", "国语流行", "粤语流行", "日系流行", "国风流行"),
    "east-asian-ballad-heritage": ("华语抒情", "粤语抒情", "日系抒情", "国风抒情", "古风", "中国风", "东方抒情"),
    "modern-rnb-neo-soul": ("r&b", "rnb", "neo-soul", "neo soul", "节奏布鲁斯", "另类r&b", "氛围r&b"),
    "soul-blues-gospel": ("soul", "blues", "gospel", "worship", "灵魂乐", "蓝调", "福音", "敬拜"),
    "cinematic-pop-ballad": ("cinematic pop", "cinematic ballad", "orchestral pop", "电影感流行", "电影感抒情", "管弦流行"),
    "cinematic-orchestral-epic": ("film score", "soundtrack", "trailer", "orchestral", "symphonic", "电影配乐", "影视配乐", "预告片", "管弦", "交响", "史诗合唱"),
    "electronic-synth-ambient-pop": ("synth-pop", "synthpop", "electropop", "dream pop", "ambient pop", "darkwave", "retrowave", "合成器流行", "电子流行", "梦幻流行", "暗潮", "复古电子", "氛围流行"),
    "jazz-swing-big-band": ("jazz", "swing", "big band", "bossa nova", "爵士", "摇摆", "大乐队", "波萨诺瓦"),
    "traditional-vocal-stage": ("crooner", "doo-wop", "a cappella", "musical theatre", "show tune", "cabaret", "音乐剧", "舞台剧", "无伴奏", "歌舞剧", "卡巴莱"),
    "hip-hop-rap": ("hip-hop", "hip hop", "rap", "trap", "drill", "lo-fi hip-hop", "嘻哈", "说唱", "陷阱", "钻头"),
    "metal-heavy-rock": ("metal", "metalcore", "hard rock", "post-hardcore", "nu-metal", "金属", "金属核", "硬摇滚", "后硬核", "新金属"),
    "pop-alternative-rock": ("pop rock", "alternative rock", "indie rock", "arena rock", "j-rock", "punk", "流行摇滚", "另类摇滚", "独立摇滚", "朋克", "后摇"),
    "contemporary-folk-acoustic": ("indie folk", "folk pop", "singer-songwriter", "acoustic pop", "当代民谣", "独立民谣", "民谣流行", "唱作人", "原声流行"),
    "roots-traditional-global": ("traditional folk", "celtic", "reggae", "maritime", "world music", "传统民乐", "凯尔特", "雷鬼", "世界音乐", "民族融合"),
    "dance-pop-disco-funk": ("dance-pop", "dance pop", "nu-disco", "disco", "funk-pop", "funk", "舞曲流行", "迪斯科", "放克"),
    "club-edm-house-trance": ("edm", "house", "trance", "hardstyle", "dubstep", "techno", "club", "浩室", " trance", "硬派", "回响贝斯", "科技舞曲", "俱乐部"),
    "country-americana": ("country", "americana", "bluegrass", "rockabilly", "乡村", "美式根源", "蓝草", "乡村摇滚"),
    "general-pop-ballad": ("pop", "ballad", "流行", "抒情", "情歌"),
}

QUERY_ALIASES = {
    "女声": "female singer soprano mezzo",
    "男声": "male singer tenor baritone",
    "男女对唱": "male female duet",
    "合唱": "choir choral ensemble",
    "纯器乐": "instrumental no vocals",
    "说唱": "rap rhythmic vocal",
    "念白": "spoken word narration",
    "钢琴": "piano",
    "电钢琴": "rhodes electric piano",
    "木吉他": "acoustic guitar",
    "电吉他": "electric guitar",
    "弦乐": "strings orchestral",
    "管弦": "orchestral strings brass",
    "铜管": "brass",
    "贝斯": "bass",
    "鼓组": "drums percussion",
    "电子鼓": "electronic drums",
    "合成器": "synth synthesizer",
    "二胡": "erhu chinese bowed string",
    "琵琶": "pipa chinese traditional",
    "笛箫": "dizi flute chinese traditional",
    "班卓": "banjo",
    "曼陀林": "mandolin",
    "忧伤": "melancholic sorrowful",
    "温暖": "warm intimate",
    "明亮": "bright uplifting",
    "史诗": "epic majestic",
    "梦幻": "dreamy ethereal",
    "暗黑": "dark ominous",
    "热血": "energetic triumphant",
    "复古": "retro vintage",
    "亲密": "intimate close",
    "空灵": "ethereal ambient",
    "慢速": "slow",
    "中速": "midtempo",
    "快速": "fast uptempo",
}

MOOD_ARCS = [
    "自动识别",
    "克制铺陈 → 温暖释放 → 余韵收束",
    "脆弱低语 → 渐强 → 宣言式高潮",
    "平静神秘 → 紧张堆叠 → 史诗爆发",
    "忧伤回望 → 希望抬升 → 治愈落地",
    "明亮轻快 → 律动推进 → 庆祝式收尾",
    "暗涌压迫 → 强烈对抗 → 决绝收束",
    "浪漫亲密 → 宽阔抒情 → 温柔回落",
    "梦幻漂浮 → 迷离扩张 → 空灵淡出",
    "热血蓄力 → 高能副歌 → 胜利定格",
    "自定义",
]

TEMPO_OPTIONS = [
    "自动识别",
    "慢速｜60–78 BPM",
    "中慢｜79–96 BPM",
    "中速｜97–115 BPM",
    "中快｜116–132 BPM",
    "快速｜133–155 BPM",
    "高速｜156–180 BPM",
    "自定义",
]
METER_OPTIONS = ["自动识别", "4/4", "3/4", "6/8", "12/8", "自由节拍/无固定律动", "自定义"]
SCENARIO_OPTIONS = [
    "自动识别",
    "流媒体完整歌曲",
    "影视剧情/片尾曲",
    "电影或游戏配乐",
    "品牌广告/产品短片",
    "短视频背景音乐",
    "现场舞台/音乐节",
    "游戏战斗/关卡循环",
    "冥想、疗愈与睡眠",
    "儿童与亲子内容",
    "自定义",
]
DURATION_OPTIONS = ["自动识别", "30–60秒", "1–2分钟", "2–3分钟", "3–4分钟", "4–5分钟", "自定义"]
TONALITY_OPTIONS = [
    "自动识别/不指定",
    "明亮大调倾向",
    "忧郁小调倾向",
    "大小调转换",
    "五声音阶/国风调式",
    "布鲁斯调式",
    "爵士扩展和声",
    "模态/氛围化和声",
    "无明确调性",
    "自定义",
]
GROOVE_OPTIONS = [
    "自动识别",
    "平稳流行律动",
    "半拍/半速重心",
    "Swing摇摆律动",
    "Shuffle切分律动",
    "四拍踩底舞曲律动",
    "Trap切分与Hi-hat滚奏",
    "Funk切分与贝斯主导",
    "拉丁/波萨律动",
    "摇滚直拍与强反拍",
    "自由节奏/氛围脉冲",
    "自定义",
]
VOCAL_OPTIONS = [
    "自动识别",
    "纯器乐｜禁止人声与歌词",
    "单人女声",
    "单人男声",
    "中性/不限定性别单人声",
    "男女对唱",
    "双女声和声",
    "双男声和声",
    "混声主唱与合唱团",
    "说唱主唱",
    "念白/旁白与音乐",
    "无伴奏合唱",
    "自定义",
]
REGISTER_OPTIONS = [
    "自动识别",
    "低沉低音区",
    "温暖中低音区",
    "自然中音区",
    "明亮中高音区",
    "高音区与假声",
    "宽音域渐进",
    "说唱/近说话音域",
    "纯器乐主旋律",
    "自定义",
]
TIMBRE_OPTIONS = [
    "自动识别",
    "清澈明亮",
    "温暖柔和",
    "气声亲密",
    "醇厚磁性",
    "沙哑颗粒感",
    "高亢有力",
    "空灵通透",
    "复古爵士",
    "灵魂乐律动感",
    "激烈嘶吼/失真",
    "自定义",
]
DELIVERY_OPTIONS = [
    "自动识别",
    "叙述式、克制",
    "细腻气声、贴耳",
    "抒情渐强、宽阔副歌",
    "强力真声与高音爆发",
    "R&B转音与即兴Ad-lib",
    "节奏说唱、吐字清晰",
    "吟唱/颂唱",
    "戏剧化音乐剧演唱",
    "合唱式群体呼应",
    "纯器乐主旋律",
    "自定义",
]
HARMONY_OPTIONS = [
    "自动识别",
    "无伴唱、单主唱",
    "副歌轻量叠唱",
    "贴近三度/六度和声",
    "宽阔多轨和声墙",
    "领唱与群体呼应",
    "男女声对位",
    "福音式合唱抬升",
    "氛围哼唱与人声Pad",
    "自定义",
]
INSTRUMENT_OPTIONS = [
    "自动识别",
    "钢琴 + 弦乐 + 克制鼓组",
    "指弹木吉他 + 轻鼓 + 温暖贝斯",
    "Rhodes电钢琴 + 圆润贝斯 + R&B鼓组",
    "合成器Pad + 琶音 + 电子鼓",
    "失真电吉他 + 贝斯 + 现场鼓组",
    "管弦乐团 + 铜管 + 合唱",
    "808贝斯 + Trap鼓组 + 氛围采样",
    "House四拍 + 贝斯线 + 合成器Lead",
    "迪斯科吉他 + 铜管 + Funk贝斯",
    "爵士钢琴 + 立式贝斯 + 刷鼓",
    "国风弦乐/笛箫 + 现代节拍",
    "二胡/琵琶 + 管弦乐",
    "班卓琴/曼陀林 + 原声乐队",
    "手碟/民族打击 + 世界音乐纹理",
    "无伴奏人声层次",
    "自定义",
]
STRUCTURE_OPTIONS = [
    "自动识别",
    "Intro → Verse → Pre-Chorus → Chorus → Verse → Chorus → Bridge → Final Chorus → Outro",
    "Intro → Verse → Chorus → Verse → Chorus → Outro",
    "Intro → Verse → Pre-Chorus → Chorus → Post-Chorus → Bridge → Final Chorus → Outro",
    "Intro → Build → Drop → Breakdown → Final Drop → Outro",
    "Intro → Rap Verse → Hook → Rap Verse → Hook → Bridge → Final Hook → Outro",
    "Intro → A段 → B段 → A'段 → B'段 → Outro",
    "Intro → Verse → Chorus → Instrumental Solo → Chorus → Outro",
    "单段循环式氛围发展",
    "自定义",
]
PRODUCTION_OPTIONS = [
    "自动识别",
    "自然有机、动态呼吸",
    "现代流行、清晰宽阔",
    "温暖复古、磁带/黑胶质感",
    "电影化宽动态与空间层次",
    "俱乐部级紧实低频与冲击力",
    "Lo-fi柔化、颗粒与轻微失真",
    "极简干净、主体靠前",
    "密集墙式音色、强压缩",
    "空灵氛围、长尾混响",
    "现场乐队、真实房间感",
    "自定义",
]
SPACE_OPTIONS = [
    "自动识别",
    "亲密近场、主唱居中",
    "适度宽声场、清晰层次",
    "大空间厅堂混响",
    "电影化深景与环绕感",
    "俱乐部直接、有力且紧实",
    "朦胧梦幻、延迟与长尾",
    "干声靠前、少量空间效果",
    "自定义",
]
DENSITY_OPTIONS = [
    "自动识别",
    "极简留白",
    "由疏到密逐步堆叠",
    "中等密度、层次清晰",
    "副歌宽阔、主歌克制",
    "持续高能密集",
    "段落间强烈疏密对比",
    "自定义",
]
DETAIL_OPTIONS = ["精简｜180–250词", "标准｜250–450词", "详细｜450–650词", "自定义"]
OUTPUT_OPTIONS = ["结构化文本", "JSON", "JSONL"]
LANGUAGE_OPTIONS = ["英文（Music 3推荐）", "中文", "双语：英文为主、中文注释"]
EXCLUSION_OPTIONS = [
    "无",
    "禁止人声",
    "禁止说唱",
    "禁止电子鼓与808",
    "禁止失真吉他",
    "禁止合唱团",
    "禁止过度混响",
    "禁止过度压缩/响度战争",
    "禁止悲伤走向",
    "禁止史诗化堆叠",
    "自定义",
]

def strip_code_fence(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        value = "\n".join(lines).strip()
    return value


def parse_json_object(text):
    cleaned = strip_code_fence(text)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for position, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(cleaned[position:])
            except json.JSONDecodeError:
                continue
            return parsed if isinstance(parsed, dict) else None
    return None


def heading_section(text, heading, following=None):
    pattern = rf"(?ims)^###?\s*{re.escape(heading)}\s*$\s*(.*?)(?=^###?\s*(?:{re.escape(following) if following else 'Global Metadata|Vocal Details|Arrangement'})\s*$|\Z)"
    match = re.search(pattern, str(text or ""))
    return match.group(1).strip() if match else ""


def make_caption(global_metadata, vocal_details, arrangement):
    return (
        "### Global Metadata\n\n"
        f"{str(global_metadata or '').strip()}\n\n"
        "### Vocal Details\n\n"
        f"{str(vocal_details or '').strip()}\n\n"
        "### Arrangement\n\n"
        f"{str(arrangement or '').strip()}"
    ).strip()


def parse_music3_output(text):
    parsed = parse_json_object(text)
    if isinstance(parsed, dict):
        global_metadata = str(parsed.get("global_metadata") or parsed.get("Global Metadata") or "").strip()
        vocal_details = str(parsed.get("vocal_details") or parsed.get("Vocal Details") or "").strip()
        arrangement = str(parsed.get("arrangement") or parsed.get("Arrangement") or "").strip()
        if global_metadata and vocal_details and arrangement:
            return {
                "caption": make_caption(global_metadata, vocal_details, arrangement),
                "global_metadata": global_metadata,
                "vocal_details": vocal_details,
                "arrangement": arrangement,
                "generated_lyrics": str(parsed.get("generated_lyrics") or "").strip(),
                "music_brief": str(parsed.get("music_brief") or "").strip(),
                "validation": str(parsed.get("validation") or "").strip(),
            }
    cleaned = strip_code_fence(text)
    global_metadata = heading_section(cleaned, "Global Metadata", "Vocal Details")
    vocal_details = heading_section(cleaned, "Vocal Details", "Arrangement")
    arrangement = heading_section(cleaned, "Arrangement")
    return {
        "caption": make_caption(global_metadata, vocal_details, arrangement) if all((global_metadata, vocal_details, arrangement)) else cleaned,
        "global_metadata": global_metadata,
        "vocal_details": vocal_details,
        "arrangement": arrangement,
        "generated_lyrics": "",
        "music_brief": "",
        "validation": "",
    }


def extract_lyric_tags(lyrics):
    tags = []
    for raw in re.findall(r"\[([^\]\r\n]{1,120})\]", str(lyrics or "")):
        tag = "[" + re.sub(r"\s+", " ", raw).strip() + "]"
        if tag not in tags:
            tags.append(tag)
    return tags


def lyric_leakage(lyrics, caption):
    normalized_caption = re.sub(r"\s+", " ", str(caption or "").lower())
    leaks = []
    for line in str(lyrics or "").splitlines():
        line = re.sub(r"\[[^\]]+\]", "", line).strip()
        normalized = re.sub(r"\s+", " ", line.lower())
        if len(normalized) >= 20 and normalized in normalized_caption:
            leaks.append(line[:80])
    return leaks[:3]


def is_instrumental_request(request, controls):
    vocal_mode = str(controls.get("人声配置") or "")
    exclusions = str(controls.get("排除项") or "")
    source = str(request or "").lower()
    explicit_phrases = (
        "纯器乐", "纯音乐", "无人声", "不要人声", "禁止人声", "无歌词",
        "instrumental only", "no vocals", "without vocals",
    )
    return (
        "纯器乐" in vocal_mode
        or "禁止人声" in exclusions
        or any(phrase in source for phrase in explicit_phrases)
    )


def validate_generated_lyrics(lyrics):
    text = str(lyrics or "").strip()
    if not text:
        raise RuntimeError("LLM没有生成歌词。")
    if not extract_lyric_tags(text):
        raise RuntimeError("LLM生成的歌词缺少[Verse]、[Chorus]等Music3段落标签。")
    lyric_body = re.sub(r"\[[^\]]+\]", "", text).strip()
    if len(lyric_body) < 12:
        raise RuntimeError("LLM生成的歌词正文过短。")
    return text


def parse_index_cards(index_path):
    cards = []
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return cards
    for line in lines:
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        template_match = re.search(r"`templates/([^`]+)`", cells[-1])
        identifier = cells[0].strip("`")
        if not template_match or not identifier:
            continue
        cards.append({
            "id": identifier,
            "style": cells[1],
            "secondary": cells[2],
            "tempo": cells[3],
            "mood": cells[4],
            "vocal": cells[5],
            "palette": cells[6],
            "template": template_match.group(1),
        })
    return cards


def keyword_tokens(text):
    source = str(text or "").lower()
    expanded = [source]
    for cue, english in QUERY_ALIASES.items():
        if cue in source:
            expanded.append(english)
    return {
        token for token in re.findall(r"[a-z0-9+#&']{2,}", str(text or "").lower())
        if token not in {"the", "and", "with", "for", "from", "into", "auto"}
    } | {
        token for token in re.findall(r"[a-z0-9+#&']{2,}", " ".join(expanded))
        if token not in {"the", "and", "with", "for", "from", "into", "auto"}
    }


def route_automatic_family(text, exclude=None):
    source = str(text or "").lower()
    scored = []
    for family, cues in AUTO_ROUTE_CUES.items():
        if family == exclude:
            continue
        score = 0
        for cue in cues:
            if re.fullmatch(r"[a-z0-9 &+.'/-]+", cue):
                matched = re.search(rf"(?<![a-z0-9]){re.escape(cue)}(?![a-z0-9])", source) is not None
            else:
                matched = cue in source
            if matched:
                score += 3 if len(cue) >= 5 else 2
        if family == "general-pop-ballad":
            score = min(score, 1)
        scored.append((score, family))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1] if scored and scored[0][0] > 0 else "general-pop-ballad"


def select_templates(families, query, maximum=3):
    tokens = keyword_tokens(query)
    ranked_by_family = []
    seen = set()
    for family in families:
        if not family or family in seen:
            continue
        seen.add(family)
        cards = parse_index_cards(RESOURCE_ROOT / "references" / f"index-{family}.md")
        scored = []
        for order, card in enumerate(cards):
            text = " ".join(card[key] for key in ("style", "secondary", "tempo", "mood", "vocal", "palette"))
            score = len(tokens & keyword_tokens(text))
            scored.append((score, -order, card))
        if scored:
            scored.sort(reverse=True)
            ranked_by_family.append([item[2] for item in scored])
    selected = []
    if ranked_by_family:
        selected.append(ranked_by_family[0][0])
    if len(ranked_by_family) > 1 and ranked_by_family[1]:
        selected.append(ranked_by_family[1][0])
    for card in ranked_by_family[0][1:] if ranked_by_family else []:
        if card["id"] not in {item["id"] for item in selected}:
            selected.append(card)
        if len(selected) >= maximum:
            break
    references = []
    for card in selected[:maximum]:
        try:
            content = (RESOURCE_ROOT / "templates" / card["template"]).read_text(encoding="utf-8").strip()
        except OSError:
            content = ""
        if content:
            references.append({"card": card, "caption": content})
    return references


def choice_with_custom(value, custom_value):
    value = str(value or "自动识别").strip()
    if value == "自定义":
        custom_value = str(custom_value or "").strip()
        if not custom_value:
            raise ValueError("已选择“自定义”，请填写对应的自定义内容。")
        return custom_value
    return value

SYSTEM_PROMPT = """You are the MiniMax Music 3 Structured Caption and lyrics compiler.

Turn a concise music request and optional lyrics into a fresh, generation-oriented Music 3 caption. Work privately: first form a Music Brief, resolve constraints, route to the supplied style family references, choose at most three references with Foundation / Modifier / Arrangement roles, then create a coherent timeline. Never reveal reference IDs, routing scores, template content, or chain of thought.

Hard rules, in priority order:
1. Preserve explicit user requirements and exclusions. Then preserve section-local bracketed lyric tags. Do not let a reference override them.
2. When source lyrics are supplied, they are immutable private analysis material: never quote, paraphrase, summarize, translate, or repeat them in the caption. Return an empty generated_lyrics field because the node preserves the original text itself. Only their bracketed tags may become section-level arrangement directives.
3. When source lyrics are absent and the request is vocal music, create a complete original lyric in generated_lyrics. Use Music3 bracketed section tags such as [Intro], [Verse 1], [Pre-Chorus], [Chorus], [Bridge], and [Outro], following the selected song structure. Match the language and subject implied by the user's request; for a primarily Chinese request with no stated lyric language, use Simplified Chinese. Do not put lyrics in any caption field.
4. When the request is instrumental or forbids vocals, generated_lyrics must be an empty string and Vocal Details must describe the lead melodic instrument or texture.
5. Do not reverse a specified vocal gender, tempo constraint, required instrument, or prohibition.
6. Do not fabricate exact BPM, key, scale, vocalist identity, or technical production claims. Use a range or qualitative description unless explicitly supplied or clearly justified by the controls.
7. References are inspiration only. Do not copy sentences, distinctive phrases, exact instrument lifecycles, or full structures. Synthesize a new result.
8. Make an audible section-by-section arrangement: explain entrances, exits, intensification, groove changes, transitions, and texture lifecycle. Do not return a static equipment list.

Return JSON only, without markdown fences, with exactly these keys:
{
  "global_metadata": "...",
  "vocal_details": "...",
  "arrangement": "...",
  "generated_lyrics": "complete tagged lyrics when source lyrics are absent and vocals are wanted; otherwise an empty string",
  "music_brief": "short non-sensitive summary of preserved user constraints only",
  "validation": "short confirmation of constraint, lyric-tag, and structure checks"
}

The three caption fields must render as exactly these headings when assembled: Global Metadata, Vocal Details, Arrangement. Do not place a song title, template ID, lyrics, or hidden reasoning in those caption fields."""
