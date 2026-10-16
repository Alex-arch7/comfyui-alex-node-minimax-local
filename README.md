# comfyui-alex-node-minimax-local

MiniMax **H3 音视频提示词编译器** + **Music 3 结构化音乐提示词** + **Qwen-Image-2.1 提示词改写**，
每个业务节点都提供 **本地 GGUF** 与 **OpenAI 兼容 API** 两个后端，节点命名统一为
`alex_XXXX_local` / `alex_XXXX_API`。

核心价值继承自 `ComfyUI-llama_Dapao` 的 MiniMax 方向：

1. **规范硬约束 + 双层审计**——官方 H3 Context-IR 字段顺序、首尾帧对齐句模板、`[Shot N] At MM:SS.mmm`
   时间戳、`<Subject/Picture/Video/Audio N>` 标签全部程序化校验；LLM 改动官方素材编号会直接熔断停止输出。
2. **前端图感知联动**——自动检测下游官方 `MiniMax H3 Image to Video` / `MiniMax H3 Reference to Video`
   节点，反读其已接素材生成「🧩H3自动素材清单」锁定编号；输入框键入 `@` 弹出官方素材引用菜单。
3. **双后端同引擎**——业务逻辑（模式判定、素材清单、媒体分析、审计、输出组装）只写一遍，
   本地/远程只是注入不同的 `client.chat(payload)`。

## 节点列表（分类 `Alex/MiniMax/…`）

| 节点 ID | 显示名 | 后端 |
|---|---|---|
| `alex_h3_prompt_local` | alex_h3_prompt_local｜H3视频提示词(本地GGUF) | llama-cpp-python 本地 GGUF |
| `alex_h3_prompt_API` | alex_h3_prompt_API｜H3视频提示词(OpenAI兼容) | OpenAI 兼容端点 |
| `alex_h3_prompt_box` | alex_h3_prompt_box｜H3专用提示词框 | 无 LLM（纯校验） |
| `alex_h3_skill_local` | alex_h3_skill_local｜H3提示词·Skill路由(本地GGUF) | 本地 GGUF |
| `alex_h3_skill_API` | alex_h3_skill_API｜H3提示词·Skill路由(OpenAI兼容) | OpenAI 兼容端点 |
| `alex_music3_local` | alex_music3_local｜Music3音乐提示词(本地GGUF) | 本地 GGUF |
| `alex_music3_API` | alex_music3_API｜Music3音乐提示词(OpenAI兼容) | OpenAI 兼容端点 |
| `alex_qwen_image21_local` | alex_qwen_image21_local｜Qwen-Image2.1提示词(本地GGUF) | 本地 GGUF |
| `alex_qwen_image21_API` | alex_qwen_image21_API｜Qwen-Image2.1提示词(OpenAI兼容) | OpenAI 兼容端点 |

## 安装

1. 将本目录放入 `ComfyUI/custom_nodes/comfyui-alex-node-minimax-local/`。
2. 安装依赖：`pip install -r requirements.txt`（`llama-cpp-python` 仅本地节点需要；
   视觉 GGUF 需要自带 `Qwen3VLChatHandler`/`Qwen25VLChatHandler` 多模态处理器的构建）。
3. 重启 ComfyUI。

## 本地节点（alex_XXXX_local）

沿用你 `ComfyUI_qwen_chat_models`（`alex_qwen_VL_model` / `alex_qwen_chat_model`）的思路：

- GGUF 与 mmproj 从 `ComfyUI/models/LLM/`（及 `llm/`）递归扫描，全部经 `folder_paths` 动态获取；
- mmproj 支持 `auto`（优先取主模型同目录的投影）/ `none` / 手动指定；
- 视觉推理通过多模态 `chat_handler`（Qwen3VL → Qwen25VL → Qwen2VL → LLaVA 逐级回退），
  纯文本模型自动回退 `chatml`；
- 所有本地节点共享一个 **常驻+LRU 模型缓存**（环境变量 `ALEX_MAX_LOADED_MODELS`，默认 2）：
  「📌常驻显存不卸载」固定模型，「🧹推理后卸载模型」推理完立即释放显存给生图/视频节点；
- 图片数量多时自动扩上下文（图像最大token × 图片数 + 输出token + 512）。

## 远程节点（alex_XXXX_API）

沿用你 `comfyui-alex-node-llm-api`（`Alex LLM API (Unified)`）的思路：

- `🔑 openai_api_key`（留空回退 `OPENAI_API_KEY` 环境变量）+ `🌐 endpoint`（默认 `https://api.openai.com/v1`）；
- 点击节点上的 **🔄 Refresh Models** 按钮，从端点 `GET /models` 拉取模型列表填充下拉框，
  并按端点持久化到插件 `cache/models.json`（重启后仍在）；
- `✍️ custom_model` 非空时覆盖下拉，可直接填任意模型 ID；
- 401/402/404/429/5xx 等错误给出中文友好提示；请求不自动重试，避免重复扣费。

## H3 编译器（核心）

- **五种模式**：T2VA / I2VA（首帧）/ FL2VA（首尾帧）/ L2VA（尾帧）/ Ref2VA（全能参考），自动识别或手动锁定；
- **官方素材上限严格执行**：9 图 + 3 视频 + 3 音频、混合文件 ≤12、单个视频/音频 2–15 秒、
  各自总时长 ≤15 秒、音频不能为唯一素材；
- **参考视频用 IMAGE 帧批次接入**（与你现有视频读取方式一致，无 cv2/imageio 解码依赖）：
  「🎬 参考视频帧率」解释时长（默认 24fps），「🎞️ 视频每秒采样帧数」控制送入 LLM 的分析帧密度；
- **参考音频**本地生成频谱图 + BPM/RMS/静音比例估算；「🎧 参考音频原声直传LLM」可把 WAV 以
  `input_audio` 送入支持音频的模型；
- **31 种创作预设**（通用H3、极简产品广告、邵氏复古武侠、赛博朋克……），每个是 10 段式创作契约；
- **中英输出策略**：中文正文时官方结构 token 保持英文原样；
- **双层审计**：字段顺序/对齐句/时间戳/素材编号越界 → 输出提醒；官方素材编号被 LLM 改动 → 直接停止输出。

### 与官方 MiniMax H3 节点联动

1. 把 `alex_h3_prompt_local`（或 `_API`）的「🎬 H3最终提示词」连到官方 H3 节点的提示词输入；
2. 前端自动识别下游官方节点及其已接素材，写入「🧩 H3自动素材清单」并锁定编号；
3. 在「📝 原始视频需求」里键入 `@` 选择 `<Picture 1>`、`<Video 1>`、`<Audio 1>` 等官方素材；
4. 也可手写提示词：用 `alex_h3_prompt_box`（📝 H3提示词 + 🧩 H3素材标记 → 官方节点），
   它同样支持 `@` 素材引用并校验标记格式与编号连续性。

### H3 Skill 路由版（alex_h3_skill_local / alex_h3_skill_API）

与旗舰编译器的「31 创作预设 + 强审计」不同，Skill 路由版由**官方 MiniMax-H3 技能库**驱动，
输出格式跟随所选 Skill 自身的 SKILL.md 指令（契约更松、风格更丰富）：

- **9 个官方 Skill** 随插件打包在 `resources/h3_skills/`（1 个 h3-prompt-writing 提示词写作 +
  8 个风格生成器：3D动画、品牌宣传片、极简产品广告、手绘直播、MV字幕、纸拼贴科普、
  纸艺定格科普、联机游戏介绍）；自定义技能放 `resources/custom_skills/`（同名目录覆盖）；
- **三段式路由**：素材数量确定性判模式（0图=T2VA、≥3图或含视频=Ref2VA）；1–2 图意图不明确时
  用一次 32-token 轻量 LLM 调用判定首帧/尾帧/通用参考；`🧩 Skill=auto` 时再用一次 96-token
  调用从技能目录自动选型（8B 级模型即可胜任路由）；
- **参考视频按秒拼 contact sheet**（每秒采样帧数可调），一次调用看完全片节奏；
- 空输出自动重试一次；`⏱️ 目标秒数` 允许 1–60 秒（直连官方 H3 节点请保持 4–15）。

#### 同步官方技能库（MiniMax-AI/MiniMax-H3）

`resources/h3_skills/` 是官方技能库随包快照，**不会自动更新**，两种同步方式：

1. **GitHub Actions 自动 PR**（本仓库已内置 `.github/workflows/sync-h3-skills.yml`）：
   每月 1 日拉取上游 `skills/`，有差异才开 PR（无差异完全静默），审查合并即可；
2. **本地脚本**（ComfyUI 机器上按需执行，纯标准库无依赖）：

   ```bash
   python tools/sync_h3_skills.py --dry-run   # 只看差异
   python tools/sync_h3_skills.py             # 应用（自动备份旧版到 resources/.h3_skills_backup_*）
   ```

   也可挂 cron：`0 9 1 * * cd .../comfyui-alex-node-minimax-local && python3 tools/sync_h3_skills.py`。
   私有仓库/限流时可设 `GITHUB_TOKEN` 环境变量提高 API 配额。

上游更新呈**阵发式**（集中在模型发布前后），月度检查足够。
新增/删除技能需重启 ComfyUI 才进下拉；仅正文变化下次运行即生效。自定义技能放
`resources/custom_skills/`，同步永远不会碰它。

## 示例工作流（`examples/`）

| 文件 | 内容 |
|---|---|
| `alex_h3_local_example.json` | 旗舰编译器基础用法 |
| `alex_h3_ref2va_official_node.json` | Ref2VA 双参考图 → 编译 → 官方 `MiniMaxH3ReferenceToVideo`（prompt + ref_image_1/2 联动）+ 分析预览 |
| `alex_h3_skill_local_example.json` | Skill 路由版：参考图 + Skill=auto 自动选型 → 预览 |

导入后把 GGUF/mmproj 下拉换成你本机的模型即可运行。

## Music3 音乐提示词

- 生成 MiniMax Music 3 三段式 caption（Global Metadata / Vocal Details / Arrangement）+ 完整歌词；
  前两个输出可直连官方 Music3 Text Encode；
- 内置本地风格库：19 个风格族路由 + 18 个族 index + 1000 条 caption 模板（`resources/music3_caption_rewriter/`），
  按需求自动选族、按关键词挑 ≤3 条参考；
- 21 项细粒度控制（每项带自定义文本框）；无歌词自动创作、有歌词原样保留且**绝不泄漏进 caption**；
  纯器乐要求强制校验。

## Qwen-Image-2.1 提示词

- 文生图 / 改图 / 多图合成 / 风格迁移等 9 种任务模式，8 个参考图接口；
- 规则库来自 `iamyoki/qwen-image-2.1-skill`（Apache-2.0，见 `resources/qwen_image_2_1/LICENSE`）；
- 输出严格 JSON 校验：`📋可用提示词`、`📐wh_ratio`、`🖼️ratio_follow`（`<imageN>` 基准图引用逐一核对）。

## 架构

```
nodes_h3.py / nodes_h3_skill.py / nodes_music3.py / nodes_qwen_image.py   ← 业务引擎（各一份）
        │  client.chat(OpenAI风格 payload)
        ├── alex_minimax/backend_local.py   ← llama.cpp + mmproj chat_handler + 共享模型缓存
        └── alex_minimax/backend_api.py     ← OpenAI兼容端点 + /models 刷新 + 磁盘缓存
alex_minimax/h3_spec.py / h3_skill_spec.py / h3_audit.py / media.py / llm_common.py / music3_spec.py   ← 共享规范与工具
resources/h3_skills/（官方9技能） / custom_skills/（自定义） / music3_caption_rewriter/ / qwen_image_2_1/
web/js/  ← 官方H3节点素材联动、@引用编辑器、Refresh Models 按钮
```

## 测试

```bash
python -B _test_smoke.py   # 58 项纯逻辑测试：审计、清单、路由、Skill库、媒体分析、缓存卸载，无需模型
python diagnose.py         # 在 ComfyUI 机器上复现导入过程，打印真实报错
```

## 常见问题排查

**1. 跑本地节点时整个 ComfyUI 崩溃（`CUDA error` / `Aborted (core dumped)`）**
llama.cpp 显存分配失败会直接 `abort()` 杀掉整个进程，Python 无法捕获。插件已内置三层防护：
- 加载前**显存预检**：估算模型+mmproj+KV缓存+计算缓冲 vs 当前 CUDA 空闲显存，不够时报中文错误并给出建议（降上下文/降图像最大token/降GPU层数/卸载生图模型），可用 `ALEX_SKIP_VRAM_CHECK=1` 跳过；
- 上下文自动扩展改为按**图片实际尺寸**估算 Qwen-VL 视觉 token（`ceil(w/28)×ceil(h/28)`，实测与 llama.cpp `image_tokens->nx/ny` 一致），不再按「图像最大token」最坏情况预留；
- 默认设置 `GGML_CUDA_NO_VMM=1`，绕开部分新驱动/CUDA 组合下有问题的 ggml VMM 池分配器。

**2. 输出出现海量空行 / 内容被截断（小模型复读循环）**
4B 级模型在 Ref2VA 长结构化输出下可能陷入换行复读。插件已：
- 本地后端默认带反复读采样：🔁重复惩罚=1.1、🎲Top_K=20、🎲Min_P=0.05（可在节点上调，反复出现建议惩罚 1.2–1.3）；
- 输出后处理自动把 3+ 连续换行压缩为空行；
- `finish_reason=length` 或检测到大量空行时，在「📑 素材与制作分析」输出里给出 ⚠️ 质量提醒（提高最大输出令牌 / 换更大模型）。

**3. API 节点报参数错误**
`seed` 字段不会发给远程端点（部分中转站会 400），随机种仅控制 ComfyUI 缓存。

## 来源与致谢

- 提示词规范、创作预设、审计与前端联动改编自 `ComfyUI-llama_Dapao`；
  Skill 路由版（含官方 MiniMax-H3 技能库）沿其 `本地H3提示词` 血统，上游为 chflame163/ComfyUI_Qwen_H3_Prompt（MIT）；
- 本地 GGUF 后端（GGUF/mmproj 扫描、多模态 chat_handler、常驻+LRU 缓存）改编自 `ComfyUI_qwen_chat_models`；
- 远程后端（key+endpoint+可刷新模型下拉）改编自 `comfyui-alex-node-llm-api`；
- H3 规范源自官方 MiniMax-H3 h3-prompt-writing skill；Qwen-Image-2.1 规则源自 iamyoki/qwen-image-2.1-skill（Apache-2.0）。
