# comfyui-alex-node-minimax-local

**English** | [简体中文](README.zh-CN.md)

> Full version history: [CHANGELOG.md](CHANGELOG.md)

MiniMax **H3 audio-visual prompt compiler** + **Music 3 structured music prompts** +
**Qwen-Image-2.1 prompt rewriting**. Every business node ships in a matched pair —
**local GGUF** and **OpenAI-compatible API** backends — named `alex_XXXX_local` / `alex_XXXX_API`.

Core value inherited from the MiniMax direction of `ComfyUI-llama_Dapao`:

1. **Hard spec constraints + dual audit** — official H3 Context-IR field order, first/last-frame
   alignment-sentence templates, `[Shot N] At MM:SS.mmm` timestamps, `<Subject/Picture/Video/Audio N>`
   labels are all validated programmatically; if the LLM tampers with official asset numbering,
   output is fused immediately.
2. **Graph-aware frontend integration** — automatically detects downstream official
   `MiniMax H3 Image to Video` / `MiniMax H3 Reference to Video` nodes, reads back their connected
   assets to build the "🧩 H3 auto asset manifest" with locked numbering; typing `@` in the input
   box pops up the official asset-reference menu.
3. **One engine, two backends** — business logic (mode detection, asset manifest, media analysis,
   audit, output assembly) is written once; local vs remote simply injects a different
   `client.chat(payload)`.

## Nodes (category `Alex/MiniMax/…`)

| Node ID | Display name | Backend |
|---|---|---|
| `alex_h3_prompt_local` | alex_h3_prompt_local｜H3 video prompt (local GGUF) | llama-cpp-python local GGUF |
| `alex_h3_prompt_API` | alex_h3_prompt_API｜H3 video prompt (OpenAI-compatible) | OpenAI-compatible endpoint |
| `alex_h3_prompt_box` | alex_h3_prompt_box｜H3 dedicated prompt box | no LLM (validation only) |
| `alex_h3_skill_local` | alex_h3_skill_local｜H3 prompt · Skill router (local GGUF) | local GGUF |
| `alex_h3_skill_API` | alex_h3_skill_API｜H3 prompt · Skill router (OpenAI-compatible) | OpenAI-compatible endpoint |
| `alex_music3_local` | alex_music3_local｜Music3 music prompt (local GGUF) | local GGUF |
| `alex_music3_API` | alex_music3_API｜Music3 music prompt (OpenAI-compatible) | OpenAI-compatible endpoint |
| `alex_qwen_image21_local` | alex_qwen_image21_local｜Qwen-Image2.1 prompt (local GGUF) | local GGUF |
| `alex_qwen_image21_API` | alex_qwen_image21_API｜Qwen-Image2.1 prompt (OpenAI-compatible) | OpenAI-compatible endpoint |

## Installation

1. Place this folder at `ComfyUI/custom_nodes/comfyui-alex-node-minimax-local/`.
2. Install dependencies: `pip install -r requirements.txt` (`llama-cpp-python` is only needed by
   local nodes; vision GGUFs require a build with the `Qwen3VLChatHandler`/`Qwen25VLChatHandler`
   multimodal chat handlers).
3. Restart ComfyUI.

## Local nodes (alex_XXXX_local)

Following the approach of `ComfyUI_qwen_chat_models` (`alex_qwen_VL_model` / `alex_qwen_chat_model`):

- GGUF and mmproj are scanned recursively from `ComfyUI/models/LLM/` (and `llm/`), always via
  `folder_paths`;
- mmproj supports `auto` (prefer the projection next to the main model) / `none` / explicit choice;
- vision inference runs through multimodal `chat_handler`s (Qwen3VL → Qwen25VL → Qwen2VL → LLaVA
  fallback chain); text-only models fall back to `chatml`;
- all local nodes share one **pinned + LRU model cache** (env `ALEX_MAX_LOADED_MODELS`, default 2):
  "📌 keep in VRAM" pins a model, "🧹 unload after inference" frees VRAM right away for
  image/video generation nodes;
- context auto-expands with many images (max image tokens × image count + output tokens + 512).

## Remote nodes (alex_XXXX_API)

Following the approach of `comfyui-alex-node-llm-api` (`Alex LLM API (Unified)`):

- `🔑 openai_api_key` (falls back to the `OPENAI_API_KEY` env var) + `🌐 endpoint`
  (default `https://api.openai.com/v1`);
- the **🔄 Refresh Models** button pulls `GET /models` from the endpoint into the dropdown and
  persists it per endpoint in `cache/models.json` (survives restarts);
- a non-empty `✍️ custom_model` overrides the dropdown with any model ID;
- 401/402/404/429/5xx errors get friendly messages; requests are never auto-retried to avoid
  duplicate billing.

## H3 compiler (flagship)

- **Five modes**: T2VA / I2VA (first frame) / FL2VA (first+last) / L2VA (last frame) /
  Ref2VA (full reference), auto-detected or manually locked;
- **Official asset limits strictly enforced**: 9 images + 3 videos + 3 audio, ≤12 mixed files,
  2–15s per clip, ≤15s totals, audio cannot be the sole media;
- **Reference videos are IMAGE frame batches** (matching existing video-loading habits, no
  cv2/imageio decoding dependency): "🎬 reference video fps" interprets duration (default 24fps),
  "🎞️ sample frames per second" controls analysis density;
- **Reference audio** gets a local spectrogram + BPM/RMS/silence-ratio estimate;
  "🎧 send raw audio to LLM" ships WAV as `input_audio` to audio-capable models;
- **31 creative profiles** (general H3, minimalist product ad, Shaw Brothers wuxia, cyberpunk…),
  each a 10-section creative contract;
- **Bilingual output policy**: with Chinese body text, official structural tokens stay English;
- **Dual audit**: field order / alignment sentences / timestamps / out-of-range numbering →
  warnings; tampered official numbering → output stopped outright.

### Wiring into official MiniMax H3 nodes

1. Connect `alex_h3_prompt_local` (or `_API`) "🎬 final H3 prompt" to the official H3 node's
   prompt input;
2. the frontend auto-detects the downstream official node and its assets, writing the
   "🧩 H3 auto asset manifest" with locked numbering;
3. type `@` in "📝 original video request" to insert `<Picture 1>`, `<Video 1>`, `<Audio 1>`, …;
4. hand-written prompts work too via `alex_h3_prompt_box` (📝 H3 prompt + 🧩 H3 asset manifest →
   official node), with the same `@` menu plus format/numbering validation.

### H3 Skill-router edition (alex_h3_skill_local / alex_h3_skill_API)

Unlike the flagship's "31 profiles + strict audit", the Skill-router edition is driven by the
**official MiniMax-H3 skill library**; output format follows the selected skill's own SKILL.md
(looser contract, richer styles):

- **9 official skills** bundled in `resources/h3_skills/` (h3-prompt-writing plus 8 style
  generators: 3D animation, brand promo, minimalist product ad, handdrawn-live, MV subtitles,
  paper-collage explainer, papercraft stop-motion, co-op game intro); custom skills go in
  `resources/custom_skills/` (same-name folders override); this repo ships the personal
  `alex-beauty-fashion` skill (distilled from a 49-clip corpus: 8 sub-genres, beat grammar,
  bilingual action library, scene cards, lighting recipes);
- **Three-stage routing**: deterministic mode from asset counts (0 images = T2VA, ≥3 images or
  any video = Ref2VA); one 32-token lightweight LLM call resolves first/last/general intent for
  1–2 images; one 96-token call auto-selects the skill when `🧩 Skill=auto` (an 8B-class model
  handles routing fine);
- **Reference videos become per-second contact sheets** (adjustable sampling), whole-film rhythm
  in one call;
- empty output retries once; `⏱️ target seconds` allows 1–60s (keep 4–15 when feeding official H3
  nodes directly).

#### Syncing the official skill library (MiniMax-AI/MiniMax-H3)

`resources/h3_skills/` is a bundled snapshot and **does not auto-update**. Two sync paths:

1. **GitHub Actions auto-PR** (built in: `.github/workflows/sync-h3-skills.yml`): pulls upstream
   `skills/` on the 1st of each month and opens a PR only when files actually changed (completely
   silent otherwise);
2. **Local script** (stdlib-only, run on the ComfyUI machine on demand):

   ```bash
   python tools/sync_h3_skills.py --dry-run   # show diff only
   python tools/sync_h3_skills.py             # apply (old copy backed up to resources/.h3_skills_backup_*)
   ```

   Cron works too: `0 9 1 * * cd .../comfyui-alex-node-minimax-local && python3 tools/sync_h3_skills.py`.
   Set `GITHUB_TOKEN` to raise API rate limits.

Upstream updates arrive in bursts (around model releases), so monthly checks suffice.
Adding/removing skills needs a ComfyUI restart (registry built at import); body-text edits take
effect on the next run. Custom skills in `resources/custom_skills/` are never touched by sync.

## Example workflows (`examples/`)

| File | Contents |
|---|---|
| `alex_h3_local_example.json` | flagship compiler basics |
| `alex_h3_ref2va_official_node.json` | Ref2VA two reference images → compile → official `MiniMaxH3ReferenceToVideo` (prompt + ref_image_1/2 wiring) + analysis preview |
| `alex_h3_skill_local_example.json` | Skill-router: reference image + Skill=auto routing → preview |

After import, switch the GGUF/mmproj dropdowns to your local models and run.

## Music3 music prompts

- Generates the MiniMax Music 3 three-part caption (Global Metadata / Vocal Details /
  Arrangement) + full lyrics; the first two outputs feed the official Music3 Text Encode directly;
- bundled local style library: 19 style-family routers + 18 family indexes + 1000 caption
  templates (`resources/music3_caption_rewriter/`), family auto-selected per request with ≤3
  keyword-matched references;
- 21 fine-grained controls (each with a custom-text override); lyrics auto-written when absent,
  preserved verbatim when present and **never leaked into the caption**; instrumental requests
  strictly validated.

## Qwen-Image-2.1 prompts

- 9 task modes (text-to-image, image editing, multi-image composition, style transfer, …) with
  8 reference-image slots;
- rule base from `iamyoki/qwen-image-2.1-skill` (Apache-2.0, see `resources/qwen_image_2_1/LICENSE`);
- strict JSON output validation: `📋usable_prompt`, `📐wh_ratio`, `🖼️ratio_follow` (every
  `<imageN>` base-image reference checked one by one).

## Architecture

```
nodes_h3.py / nodes_h3_skill.py / nodes_music3.py / nodes_qwen_image.py   ← business engines (one each)
        │  client.chat(OpenAI-style payload)
        ├── alex_minimax/backend_local.py   ← llama.cpp + mmproj chat_handler + shared model cache
        └── alex_minimax/backend_api.py     ← OpenAI-compatible endpoint + /models refresh + disk cache
alex_minimax/h3_spec.py / h3_skill_spec.py / h3_audit.py / media.py / llm_common.py / music3_spec.py   ← shared specs & utilities
resources/h3_skills/ (9 official skills) / custom_skills/ (user skills) / music3_caption_rewriter/ / qwen_image_2_1/
web/js/  ← official H3 asset wiring, @-reference editor, Refresh Models button
```

## Tests

```bash
python -B _test_smoke.py   # 62 model-free logic tests: audit, manifests, routing, skill library, media, cache offload
python diagnose.py         # reproduce the import on the ComfyUI machine and print the real traceback
```

## Troubleshooting

**1. Whole ComfyUI crashes on local nodes (`CUDA error` / `Aborted (core dumped)`)**
llama.cpp calls `abort()` on VRAM allocation failure, killing the process — uncatchable in Python.
Three layers of protection are built in:
- **VRAM preflight** before loading: model + mmproj + KV cache + compute buffers vs current free
  CUDA memory; insufficient VRAM raises a friendly error with remedies (lower context / lower
  max-image-tokens / fewer GPU layers / unload image models). Skip with `ALEX_SKIP_VRAM_CHECK=1`;
- context auto-expansion now estimates Qwen-VL vision tokens from **actual image sizes**
  (`ceil(w/28)×ceil(h/28)`, verified against llama.cpp `image_tokens->nx/ny`), instead of
  worst-case per-image budgets;
- `GGML_CUDA_NO_VMM=1` is set by default, bypassing the buggy ggml VMM pool allocator on some
  driver/CUDA combinations.

**2. Massive blank lines / truncated output (small-model repetition loops)**
4B-class models can fall into newline repetition on long Ref2VA structured output. Built in:
- anti-repetition sampling defaults on local backend: 🔁repeat penalty 1.1, 🎲Top_K 20,
  🎲Min_P 0.05 (tunable per node; raise penalty to 1.2–1.3 if loops persist);
- post-processing collapses 3+ consecutive newlines;
- `finish_reason=length` or heavy blank-run detection surfaces a ⚠️ quality warning in the
  analysis output (raise max tokens / use a bigger model).

**3. API nodes rejecting parameters**
The `seed` field is never sent to remote endpoints (some proxies 400 on it); the seed widget only
controls ComfyUI caching.

## Credits

- prompt spec, creative profiles, audit and frontend wiring adapted from `ComfyUI-llama_Dapao`;
  the Skill-router edition (with the official MiniMax-H3 skill library) follows its
  `本地H3提示词` lineage, upstream chflame163/ComfyUI_Qwen_H3_Prompt (MIT);
- local GGUF backend (GGUF/mmproj scanning, multimodal chat_handlers, pinned+LRU cache) adapted
  from `ComfyUI_qwen_chat_models`;
- remote backend (key + endpoint + refreshable model dropdown) adapted from
  `comfyui-alex-node-llm-api`;
- H3 spec originates from the official MiniMax-H3 h3-prompt-writing skill; Qwen-Image-2.1 rules
  from iamyoki/qwen-image-2.1-skill (Apache-2.0).
