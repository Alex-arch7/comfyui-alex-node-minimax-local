# Changelog 版本记录

All notable changes to this project are documented here.
本项目的所有重要变更记录于此。

Format: [Keep a Changelog](https://keepachangelog.com/), versions follow SemVer.

## [0.2.2] - 2026-10-16

### Fixed
- `alex_h3_skill_API` now shows the **🔄 Refresh Models** button (was missing from the frontend
  whitelist).
- `alex_h3_skill_API` 现在正确显示 **🔄 Refresh Models** 按钮（此前前端白名单遗漏）。

## [0.2.1] - 2026-10-16

### Added
- Skill-library sync tooling: `tools/sync_h3_skills.py` (stdlib-only, `--dry-run`, auto backup)
  plus a monthly GitHub Actions workflow that opens a PR only when upstream
  `MiniMax-AI/MiniMax-H3 skills/` actually changed.
- Custom skill **`alex-beauty-fashion`**: beauty/fashion portrait shorts distilled from a personal
  49-clip corpus — 8 sub-genres, duration beat-grammar, 25 bilingual action chains, 10 scene
  cards, 5 lighting recipes, compact H3 field contract.
- 技能库同步工具：本地脚本 + 每月自动检查上游的 Actions 工作流（无差异完全静默）。
- 专属技能 **`alex-beauty-fashion`**（美女时尚写真）：49 条语料提炼的 8 大子类型、节拍语法、
  25 条中英动作链、10 张场景卡、5 套布光配方。

### Tests
- 58 → 62 smoke tests (custom-skill discovery, reference injection, router catalog).

## [0.2.0] - 2026-10-09

### Added
- **`alex_h3_skill_local` / `alex_h3_skill_API`**: Skill-router H3 edition driven by the official
  MiniMax-H3 skill library (9 skills bundled), three-stage routing (deterministic mode →
  32-token mode router → 96-token skill router), per-second video contact sheets, empty-output
  retry.
- Example workflows: Ref2VA wiring into the official `MiniMaxH3ReferenceToVideo` node, and a
  Skill-router demo.
- Skill 路由版双节点：官方 MiniMax-H3 技能库驱动，三段式路由，参考视频按秒拼 contact sheet。
- 新增示例工作流：Ref2VA 官方节点联动、Skill 路由演示。

### Tests
- 42 → 58 smoke tests (skill registry, mode/skill routing, contact sheets).

## [0.1.3] - 2026-10-09

### Fixed
- Dict-shaped `h3_prompt` (nested object or wrapper-less six-field JSON returned by smaller
  models) is now rendered into the official field-per-line format instead of a Python-dict repr
  blob; semicolon lists in `subject_definitions` / `retention_analysis` split onto lines.
- 小模型返回 dict 形态的 `h3_prompt` 时，输出从"Python 字典 repr 一坨"改为官方逐字段换行格式；
  主体定义/保留分析的分号列表自动拆行。

### Added
- Audit now flags non-official timestamps (`At 0:15`) for format deviation and duration overflow.
- 审计新增非官方时间戳（如 `At 0:15`）的格式与越界检查。

## [0.1.2] - 2026-10-09

### Fixed
- **🧹 unload-after-inference actually unloads now**: cache release uses the exact stored key
  (rebuilding from `llm.n_ctx` drifted across llama-cpp builds, silently unloading nothing);
  robust unload closes the model, frees ctx/model as fallback, drops the vision-tower handler
  reference, then GC + `torch.cuda.empty_cache()` + ComfyUI `soft_empty_cache`.
- **「🧹推理后卸载模型」真正生效**：释放缓存改用加载时存下的精确 key（旧代码按 `llm.n_ctx`
  重建 key，跨 llama-cpp 版本会漂移导致静默不卸载）；卸载流程加固并输出确认日志。
- VRAM preflight no longer false-fails on cache hits (a resident model allocates nothing new).
- 显存预检在缓存命中时跳过，不再误报"显存不足"。

### Added
- VRAM preflight before cold loads (model + mmproj + KV + buffers vs free VRAM, with remedies;
  `ALEX_SKIP_VRAM_CHECK=1` to bypass).
- Vision-token estimation from real image sizes (`ceil(w/28)×ceil(h/28)`) replaces worst-case
  context inflation.
- `GGML_CUDA_NO_VMM=1` default to dodge the buggy ggml VMM pool allocator.
- Anti-repetition sampling defaults (repeat penalty 1.1 / top_k 20 / min_p 0.05) + blank-run
  collapse + `finish_reason=length` quality warnings — fixes 4B-model newline repetition floods.
- 冷加载前显存预检、按图片实际尺寸估算视觉 token、`GGML_CUDA_NO_VMM=1` 默认开启、
  反复读采样与空行压缩、截断质量提醒。

## [0.1.0] - 2026-10-09

### Added
- Initial release: 7 nodes — `alex_h3_prompt_local/_API/_box`, `alex_music3_local/_API`,
  `alex_qwen_image21_local/_API`; one engine per business with injected local (llama.cpp GGUF +
  mmproj chat_handler chain) / OpenAI-compatible backends.
- Official H3 Context-IR spec with dual audit (warnings + numbering-tamper fuse), 31 ten-section
  creative profiles, graph-aware frontend (auto asset manifest, `@`-reference menu, Refresh
  Models dropdown with per-endpoint disk cache).
- Music3 three-part caption + lyrics pipeline with 19-family/1000-template local style library;
  Qwen-Image-2.1 nine task modes with strict JSON validation.
- Import hardening with per-module tracebacks, `diagnose.py`, `MANIFEST.sha256` integrity file.
- 首发：7 节点、双后端同引擎、H3 官方规范双层审计、31 创作契约、前端图感知联动、
  Music3 风格库、Qwen-Image-2.1 严格校验、导入加固与诊断脚本。
