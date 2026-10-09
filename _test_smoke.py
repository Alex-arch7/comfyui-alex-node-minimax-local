"""Smoke tests for comfyui-alex-node-minimax-local (no ComfyUI / no model needed).

Run:  python -B _test_smoke.py
Covers the deterministic core value: H3 Context-IR audits, reference-manifest
locking, compiler-output parsing, Music 3 routing/parsing and media analysis.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from alex_minimax import h3_spec, h3_audit, llm_common, music3_spec, media

FAILURES = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILURES.append(name)


# ---------------------------------------------------------------- h3_spec
check("h3_spec: 31 creative profiles", len(h3_spec.STYLE_OPTIONS) == 31)
check("h3_spec: profiles dict matches options", set(h3_spec.STYLE_OPTIONS) == set(h3_spec.CREATIVE_PROFILES))
rendered = h3_spec.render_creative_profile("通用H3")
check("h3_spec: profile renders 10 sections", rendered.count(":") >= 10 and "适用目标" in rendered)
check("h3_spec: system prompt is Context-IR compiler", "MiniMax H3 Context-IR" in h3_spec.SYSTEM_PROMPT)
check("h3_spec: chinese language policy keeps structural tokens",
      "OUTPUT LANGUAGE POLICY" in h3_spec.LANGUAGE_POLICY_CHINESE
      and "structural tokens" in h3_spec.LANGUAGE_POLICY_CHINESE)

# ---------------------------------------------------------------- h3_audit
valid_i2va = (
    "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n"
    "integrated_multimodal_description:\nA woman turns toward the window. [Shot 2] At 00:02.500 the camera pushes in.\n"
    "overall_soundscape:\nSoft room tone.\n"
    "non_diegetic_music:\nN/A"
)
check("h3_audit: valid I2VA prompt passes", h3_audit.audit_h3_prompt(valid_i2va, "I2VA", 5.0, 1, 0, 0) == [])

bad_order = (
    "integrated_multimodal_description:\nSomething.\n"
    "non_diegetic_music:\nN/A\n"
    "overall_soundscape:\nRoom tone."
)
issues = h3_audit.audit_h3_prompt(bad_order, "T2VA", 5.0, 0, 0, 0)
check("h3_audit: field order violation detected", any("顺序" in issue for issue in issues))

late_cut = (
    "integrated_multimodal_description:\n[Shot 2] At 00:06.000 late cut.\n"
    "overall_soundscape:\nN/A\nnon_diegetic_music:\nN/A"
)
issues = h3_audit.audit_h3_prompt(late_cut, "T2VA", 5.0, 0, 0, 0)
check("h3_audit: timestamp beyond duration detected", any("超出" in issue for issue in issues))

manifest_value = json.dumps({
    "version": 1, "mode": "Ref2VA", "target": "MiniMaxH3ReferenceToVideo",
    "items": [
        {"kind": "Picture", "index": 1, "token": "<Picture 1>", "label": "参考图1", "source_input": "images1"},
        {"kind": "Audio", "index": 1, "token": "<Audio 1>", "label": "参考音频1", "source_input": "audios1"},
    ],
})
manifest = h3_audit.parse_reference_manifest(manifest_value)
check("h3_audit: manifest parsed with counts", manifest and manifest["counts"] == {"Picture": 1, "Video": 0, "Audio": 1})

bad_manifest = json.dumps({"mode": "T2VA", "items": [{"kind": "Picture", "index": 1}]})
try:
    h3_audit.parse_reference_manifest(bad_manifest)
    check("h3_audit: T2VA manifest with items rejected", False)
except ValueError:
    check("h3_audit: T2VA manifest with items rejected", True)

gap_manifest = json.dumps({"mode": "Ref2VA", "items": [
    {"kind": "Picture", "index": 1}, {"kind": "Picture", "index": 3},
    {"kind": "Video", "index": 1},
]})
try:
    h3_audit.parse_reference_manifest(gap_manifest)
    check("h3_audit: non-contiguous numbering rejected", False)
except ValueError:
    check("h3_audit: non-contiguous numbering rejected", True)

ref_prompt = "uses <Picture 1> and <Audio 1> together"
check("h3_audit: manifest audit clean on match", h3_audit.audit_reference_manifest(ref_prompt, manifest) == [])
check("h3_audit: manifest audit detects missing label",
      len(h3_audit.audit_reference_manifest("uses only <Picture 1>", manifest)) == 1)

# ---------------------------------------------------------------- llm_common
response_shape = {"choices": [{"message": {"content": "hello"}}]}
check("llm_common: extract_text from chat shape", llm_common.extract_text(response_shape) == "hello")
fenced = "```json\n{\"mode\": \"I2VA\", \"h3_prompt\": \"integrated_multimodal_description:\\nx\", \"material_analysis\": \"a\", \"production_notes\": \"b\"}\n```"
compiled = llm_common.parse_h3_compiler_output(fenced, "T2VA")
check("llm_common: fenced JSON parsed", compiled["mode"] == "I2VA" and compiled["h3_prompt"].startswith("integrated"))
plain = llm_common.parse_h3_compiler_output("just prose", "T2VA")
check("llm_common: non-JSON falls back to prose", plain["h3_prompt"] == "just prose")

# ---------------------------------------------------------------- music3_spec
check("music3_spec: jazz routing cue", music3_spec.route_automatic_family("一首摇摆爵士大乐队") == "jazz-swing-big-band")
check("music3_spec: trap routing cue", music3_spec.route_automatic_family("trap 说唱 808") == "hip-hop-rap")
references = music3_spec.select_templates(["jazz-swing-big-band"], "warm brass swing female singer")
check("music3_spec: local templates selected from library", 1 <= len(references) <= 3 and references[0]["caption"])
parsed = music3_spec.parse_music3_output(json.dumps({
    "global_metadata": "A", "vocal_details": "B", "arrangement": "C",
    "generated_lyrics": "[Verse 1]\nla la la la la la la la la la la", "music_brief": "", "validation": "",
}))
check("music3_spec: three-part caption assembled", "### Global Metadata" in parsed["caption"] and parsed["arrangement"] == "C")
leaky_caption = parsed["caption"] + "\nla la la la la la la la la la la"
check("music3_spec: lyric leakage detected when caption quotes lyrics",
      music3_spec.lyric_leakage("la la la la la la la la la la la", leaky_caption) != [])
check("music3_spec: clean caption reports no leakage",
      music3_spec.lyric_leakage("la la la la la la la la la la la", parsed["caption"]) == [])
check("music3_spec: instrumental request detected",
      music3_spec.is_instrumental_request("纯器乐", {"人声配置": "自动识别", "排除项": "无"}))
check("music3_spec: custom choice requires text",
      music3_spec.choice_with_custom("自动识别", "") == "自动识别")
try:
    music3_spec.choice_with_custom("自定义", "")
    check("music3_spec: empty custom value rejected", False)
except ValueError:
    check("music3_spec: empty custom value rejected", True)

# ---------------------------------------------------------------- media
sample_rate = 16000
seconds = 3
t = np.linspace(0, seconds, sample_rate * seconds, endpoint=False)
tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
audio_input = {"waveform": tone.reshape(1, 1, -1), "sample_rate": sample_rate}
analyzed = media.analyze_audio(audio_input, 1, include_raw_audio=True)
check("media: audio duration/spectrogram/raw wav", abs(analyzed["duration"] - seconds) < 0.01
      and analyzed["spectrogram_uri"].startswith("data:image/jpeg;base64,")
      and len(analyzed["raw_wav_base64"]) > 100)

try:
    media.normalize_audio({"waveform": tone.reshape(1, 1, -1)[:1, :, :sample_rate], "sample_rate": sample_rate}, 1)
    check("media: too-short audio rejected", False)
except ValueError:
    check("media: too-short audio rejected", True)


class _FakeFrameTensor:
    """Mimics a torch IMAGE tensor slice with detach().cpu().numpy()."""

    def __init__(self, array):
        self._array = array

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class _FakeVideoTensor:
    def __init__(self, frames):
        self.frames = frames
        self.shape = (len(frames), 8, 8, 3)

    def __getitem__(self, index):
        return _FakeFrameTensor(self.frames[index])


video = _FakeVideoTensor([np.full((8, 8, 3), value / 255.0, dtype=np.float32) for value in range(48)])
video_info = media.analyze_video_tensor(video, 1, fps=24.0, sample_frames_per_second=2)
check("media: video batch analyzed (48f/24fps=2s)", abs(video_info["duration"] - 2.0) < 0.01
      and len(video_info["frames"]) >= 2)

try:
    media.analyze_video_tensor(_FakeVideoTensor([np.zeros((8, 8, 3), dtype=np.float32)] * 12), 1, 24.0, 2)
    check("media: 0.5s video rejected", False)
except ValueError:
    check("media: 0.5s video rejected", True)

# ---------------------------------------------------------------- degeneration guards
cleaned, removed = llm_common.collapse_blank_runs("a\n\n\n\n\nb" + "\n" * 300 + "c")
check("llm_common: blank runs collapsed", cleaned.startswith("a\n\nb") and removed > 300)
check("llm_common: finish_reason extracted",
      llm_common.extract_finish_reason({"choices": [{"finish_reason": "length"}]}) == "length")

from alex_minimax.backend_local import estimate_vision_tokens  # folder_paths now optional

from alex_minimax.media import pil_to_data_uri
from PIL import Image
small_uri = pil_to_data_uri(Image.new("RGB", (392, 588)), max_side=2048, quality=90)
messages = [{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": small_uri}},
    {"type": "text", "text": "hi"},
]}]
estimated = estimate_vision_tokens(messages, image_min=1024, image_max=4096, qwen_style=True)
check("backend_local: qwen vision tokens estimated from real size (~294 clamped to min 1024)",
      estimated == 1024)
estimated_low_min = estimate_vision_tokens(messages, image_min=1, image_max=8192, qwen_style=True)
check("backend_local: qwen estimate matches nx*ny patches (14*21=294)", estimated_low_min == 294)
estimated_llava = estimate_vision_tokens(messages, image_min=1, image_max=4096, qwen_style=False)
check("backend_local: non-qwen handlers keep worst-case", estimated_llava == 4096)

# ---------------------------------------------------------------- offload / cache
from alex_minimax.backend_local import ModelCache

cache = ModelCache()

class _FakeLlamaWithClose:
    def __init__(self):
        self.closed = False
        self._chat_handler = object()

    def close(self):
        self.closed = True

class _FakeFreeable:
    def __init__(self):
        self.freed = False

    def free(self):
        self.freed = True

class _FakeLlamaNoClose:
    def __init__(self):
        self._ctx = _FakeFreeable()
        self._model = _FakeFreeable()

holder = {}
key = "/models/x.gguf|ctx8192|mmproj/mm.gguf"
model_a = _FakeLlamaWithClose()
cache.get(key, "gguf", "fam", lambda: {"model": model_a})
check("backend_local: cache hit detected", cache.has(key, "gguf", "fam"))
cache.release(key, "gguf", "fam", offload_after_used=True)
check("backend_local: offload closes model and evicts entry",
      model_a.closed and not cache.has(key, "gguf", "fam"))

model_b = _FakeLlamaNoClose()
cache.get(key, "gguf", "fam", lambda: {"model": model_b})
cache.release(key, "gguf", "fam", offload_after_used=True)
check("backend_local: no-close fallback frees ctx and model",
      model_b._ctx.freed and model_b._model.freed and not cache.has(key, "gguf", "fam"))

model_c = _FakeLlamaWithClose()
cache.get(key, "gguf", "fam", lambda: {"model": model_c})
cache.release(key, "gguf", "fam", offload_after_used=False)
check("backend_local: offload=False keeps model cached",
      not model_c.closed and cache.has(key, "gguf", "fam"))

# ---------------------------------------------------------------- summary
print()
if FAILURES:
    print(f"❌ {len(FAILURES)} failure(s): {FAILURES}")
    sys.exit(1)
print("✅ all smoke tests passed")
