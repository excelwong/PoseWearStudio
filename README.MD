# PoseWear Studio（衣姿工坊）运行说明

输入一张人物正面照片，选服装、选姿态、选输出比例，用本机 ComfyUI 生成指定画幅的高清写实人像。

> **一句话结论**：默认的 Qwen-Image 2.1 路径需要 **1 个足够新的 ComfyUI + 3 个模型文件**，
> **不需要任何第三方插件**，也**不需要导入任何工作流文件**（工作流由 App 用代码动态生成）。
> 选到 `H3：16/18/20MP` 三档时自动切换 **MiniMax-H3-Image**，另需它的 3 个模型文件
> （节点是 ComfyUI 核心内置，同样不需要插件）；详见 **3.7 节**。
>
> 本文提到的所有大小均为十进制 GB（1 GB = 10⁹ 字节）。

---

## 1. 工作原理

```
PoseWear Studio (PyQt6 桌面窗口)
        │  HTTP  http://127.0.0.1:8188
        ▼
本机 ComfyUI 服务
  /upload/image  上传「人物 / 服装 / 姿态」1~3 张参考图
  /prompt        提交由 workflow.py 动态生成的 API 格式工作流
  /history/{id}  轮询执行结果
  /view          取回生成的 PNG
  /queue         /system_stats   队列与状态
  /interrupt     中断任务
        ▼
  保存到项目 output/
```

App 使用的节点链路（`workflow.py` 的 `build()` 生成）：

```
UNETLoader ──→ QwenImage21Cache ──────────────→ KSampler ←── EmptyLatentImage(指定宽高)
CLIPLoader  ─┐                                    │
(type=qwen_image)                               ├─→ VAEDecode ─→ SaveImage
VAELoader ──┴→ TextEncodeQwenImage21 ───────────┘
              ↑
        LoadImage ×1~3 → images.image_1 / _2 / _3
        prompt 中用 <image1> <image2> <image3> 按上传顺序引用
```

选中 16 / 18 / 20 MP 三档时改由 `h3_workflow.py` 的 `build_h3()` 生成 H3 链路：

```
UNETLoader(H3 DiT) ──────────────────────────────────────→ KSampler
CLIPLoader(type=minimax) ─┐                                 │ positive
VAELoader(H3 VAE) ────────┴→ MiniMaxH3ImageConditioning ────┤ latent（节点自带目标宽高）
                            ↑ LoadImage ×1~3 → images.image_1/_2/_3
                              prompt 中用 <Picture 1> <Picture 2> <Picture 3> 引用
                          ConditioningZeroOut(positive) ────→ KSampler.negative
                          KSampler(6 步 / CFG 1) → VAEDecode → SaveImage
```

**因此 `workflows/` 目录里的 `.json` 只是参考与备份，删掉它们 App 照样能跑。**

---

## 2. 环境要求

| 项目 | 要求 | 本机实测值 |
|---|---|---|
| ComfyUI | **≥ v0.37.0**（Qwen-Image 2.1 节点随该版本加入） | 0.42.5 |
| Python | 与 ComfyUI 同一个解释器，需有 `PyQt6` / `Pillow` / `requests` | 3.13.11，torch 2.9.1+cu130 |
| GPU | 建议 ≥ 16 GB 显存；24 GB 可直出到 4K | RTX 5090 Laptop 24 GB |
| 服务端口 | `127.0.0.1:8188`，且允许本机直连（不走代理） | 8188 |
| 素材库 | 项目内 `服装库/` 与 `姿态库/`（含 `_metadata.csv`） | 1407 件服装 / 1439 张姿态 |
| 操作系统 | Windows（本项目的 `run.bat` 为 Windows 批处理） | Windows |

App 侧 Python 依赖检查：

```bash
C:\AI\ComfyUI-aki-v3\python\python.exe -c "import PyQt6, PIL, requests; print('OK')"
```

---

## 3. 必需模型（默认 Qwen 路径 3 个文件）

模型仓库：**<https://huggingface.co/Comfy-Org/Qwen-Image-2.1>**
国内镜像：**<https://hf-mirror.com/Comfy-Org/Qwen-Image-2.1>**
官方教程：**<https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1>**

### 3.1 官方原版三件套（推荐，最易复现）

| 用途 | 文件名 | 放到 ComfyUI 的 | 大小 |
|---|---|---|---|
| 扩散模型 | `qwen_image_2.1_int8_convrot.safetensors` | `models/diffusion_models/` | 7.26 GB |
| 文本编码器 | `qwen3vl_8b_int8_convrot.safetensors` | `models/text_encoders/` | 9.35 GB |
| VAE | `qwen_image_2.1_vae_bf16.safetensors` | `models/vae/` | 0.68 GB |

合计约 **17.3 GB**。文本编码器是 Qwen3-VL 8B，**必须**在 `CLIPLoader` 里把 `type` 设为 `qwen_image`。

**直接下载地址**（把域名换成 `hf-mirror.com` 即为国内镜像）：

```
https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors?download=true
https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors?download=true
https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors?download=true
```

用命令行下载（在 ComfyUI 根目录执行；国内把 `HF_ENDPOINT` 设为镜像）：

```bash
pip install -U huggingface_hub

hf download Comfy-Org/Qwen-Image-2.1 diffusion_models/qwen_image_2.1_int8_convrot.safetensors --local-dir ./models
hf download Comfy-Org/Qwen-Image-2.1 text_encoders/qwen3vl_8b_int8_convrot.safetensors   --local-dir ./models
hf download Comfy-Org/Qwen-Image-2.1 vae/qwen_image_2.1_vae_bf16.safetensors              --local-dir ./models

# 国内加速
set HF_ENDPOINT=https://hf-mirror.com
```

> ⚠️ **两个常见坑**
> 1. 官方仓库路径是 `diffusion_models/...`、`text_encoders/...`、`vae/...`，**没有 `split_files/` 前缀**。
>    网上部分教程里的 `split_files/...` 是 Qwen-Image 1.0 时代的结构，照抄会 404。
> 2. **VAE 必须用 2.1 版**。旧版 `qwen_image_vae.safetensors` 只有 3 通道，无法解码 2.1 的 4 通道 RGBA 潜变量。
> 3. 放好文件后要**重启 ComfyUI**，模型下拉列表只在启动时扫描一次。

### 3.2 本机当前使用的三件套（社区变体，`config.py` 的默认值）

本机装的是第三方量化 / 破限版本，文件名与官方不同：

| 用途 | 本机文件（相对 `models/`） | 大小 | 来源 |
|---|---|---|---|
| 扩散模型 | `diffusion_models/qwen-image-2.1-UC-int8_convrot.safetensors` | 7.26 GB | <https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-Quantized> |
| 文本编码器 | `text_encoders/qwen_image_2.1/qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors` | 10.98 GB | 社区 INT8 ConvRot 量化版，原始模型 <https://huggingface.co/DreamFast/Qwen3-VL-8B-Heretic-1.3.0>；转换发布页见 <https://civitaiarchives.com/models/2955374?modelVersionId=3347601> |
| VAE | `vae/qwen_image_2.1_vae_bf16.safetensors` | 0.68 GB | 与官方同名同大小，即官方文件 |

合计约 **18.9 GB**。

> 说明：扩散模型文件名和体积与 `abenzerps` 仓库列出的 INT8 ConvRot 版完全吻合，来源可确认；
> 文本编码器的文件名与体积和公开的量化发布条目略有出入，**未能 100% 确认具体出处**。
> 如需可复现、合规的安装，建议直接改用 3.1 的官方三件套。

### 3.3 切换到官方模型（无需改代码）

`config.json` 会覆盖 `config.py` 里 `DEFAULTS` 的同名键，所以在项目根的 `config.json` 里加三个键即可（已实测生效）：

```json
{
  "comfy_url": "http://127.0.0.1:8188",
  "library_root": ".",
  "megapixels": 2.4,
  "steps": 25,
  "cfg": 1.0,
  "ref_resolution": 1024,
  "page_size": 60,

  "unet": "qwen_image_2.1_int8_convrot.safetensors",
  "clip": "qwen3vl_8b_int8_convrot.safetensors",
  "vae": "qwen_image_2.1_vae_bf16.safetensors"
}
```

`clip` 的值可以是 `text_encoders/` 下的相对路径（如 `qwen_image_2.1\xxx.safetensors` 表示子目录）。
采样参数保持官方推荐值：**steps 25 / CFG 1.0 / euler / simple**。CFG 不要乱调，官方说明 1.0 是标准值。

### 3.4 可选模型（都不是运行必需）

都在同一个仓库 <https://huggingface.co/Comfy-Org/Qwen-Image-2.1>：

| 文件 | 用途 | 大小 |
|---|---|---|
| `diffusion_models/qwen_image_2.1_bf16.safetensors` | 全精度扩散模型，画质上限更高、显存更大 | 14.23 GB |
| `text_encoders/qwen3vl_8b_bf16.safetensors` | 全精度文本编码器 | 17.53 GB |
| `text_encoders/qwen3vl_8b_w4a8.safetensors` | 低显存文本编码器 | 6.31 GB |
| `diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors` | Turbo 蒸馏版，8 步出图 | 7.26 GB |
| `text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | 提示词增强（图像编辑） | 9.47 GB |
| `loras/qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors` | 加速 LoRA | 0.87 GB |

### 3.5 界面模型下拉与联动默认值（2026-11-10 新增）

「分辨率与参数」tab 的「生成参数」里有三个模型下拉，选项定义在 `config.py` 的
`UNET_MODELS` / `CLIP_MODELS` / `VAE_MODELS`，**显示名**与**传给 ComfyUI 的名字**分开：

| 下拉 | 可选值（界面显示名） | 实际传给 ComfyUI |
|---|---|---|
| 基模 | `qwen-image-2.1-UC-int8_convrot.safetensors`、`qwen-image-2.1-UC-Q4_K_M.gguf`、`qwen-image-2.1-turbo-Q4_K_M.gguf` | 同名，位于 `models/diffusion_models/` |
| Text Encoder | `qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors`、`qwen3vl_8b_int8_convrot.safetensors`、`qwen3vl_8b_w4a8.safetensors` | 带 `qwen_image_2.1\` 前缀，位于 `models/text_encoders/qwen_image_2.1/` |
| VAE | `qwen_image_2.1_vae_bf16.safetensors`、`[H3] minimax_h3_image_vae_fp16.safetensors` | 同名，位于 `models/vae/` |

**基模联动会一次套用五项推荐值**（`config.py` 的 `UNET_DEFAULTS`：Text Encoder、
步数、生成分辨率档位、VAE、CFG）。启动时按当前基模套用一次，之后每次切换基模再套用一次；
手工改过的值在下次切换基模前都不会被覆盖。带 `[H3] ` 前缀的三项是
MiniMax-H3-Image 专用（见 3.7 节），由分辨率档位自动选中。

| 基模 | Text Encoder 默认 | 步数默认 | 生成分辨率默认 |
|---|---|---|---|
| `qwen-image-2.1-UC-int8_convrot.safetensors` | `qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors` | 25 | `标准：2.4MP` |
| `qwen-image-2.1-UC-Q4_K_M.gguf` | `qwen3vl_8b_int8_convrot.safetensors` | 25 | `低显存：1MP` |
| `qwen-image-2.1-turbo-Q4_K_M.gguf` | `qwen3vl_8b_w4a8.safetensors` | 8 | `低显存：0.6MP` |
| `[H3] minimax_h3_image_pruned_int8_convrot.safetensors` | `[H3] qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | 6 | `H3：16MP` |

> 档位名必须与 `resolution.py` 的 `TIERS` 键逐字一致；统一格式为「名称：数值MP」
> （全角冒号、数值与 MP 之间不留空格，如 `标准：2.4MP`）；
> `config.json` 里的 `megapixels` 在启动时会被当前基模的推荐档位覆盖，
> 想用其它档位就在启动后手工改，只要不切换基模就一直生效。

三个 Text Encoder 现在都各自有对应基模；Turbo 只靠 8 步加速，CFG 仍是 1.0、euler / simple，
两个 UC 版都是 25 步。`*.gguf` 基模（UC-Q4_K_M 与 Turbo）会自动改走 `UnetLoaderGGUF`，
不需要在界面上另选工作流。切换档位会同步刷新「输出画幅比例」下方的分辨率备注与生成任务的
`megapixels`。**切到 16/18/20 MP 档位时另有一层「档位 → 引擎」联动**：自动换上
H3 三件套、6 步 / CFG 1，并把提示词重建为英文（详见 3.7 节）；切回其它档位则恢复
Qwen 默认三件套与 25 步。默认启动值仍是 Qwen + `标准：2.4MP`，没有变化。

### 3.6 低显存分辨率档位

「生成分辨率」下拉在原有 5 档之外新增两档，面向 **6 GB 显存**的机器：

| 档位 | 2:3 下实际尺寸 | 说明 |
|---|---|---|
| `低显存：1MP` | 832 × 1248 | 约 1.04 MP |
| `低显存：0.6MP` | 640 × 960 | 约 0.61 MP |

定义在 `resolution.py` 的 `TIERS`；显存不足时 `tier_steps()` 在 **Qwen 档位内**按
9.4 → 7.2 → 5.3 → 2.4 → 1.5 → 1.0 → 0.6 逐档自动降级重试（不会跨到 H3 档）。
**低显存档位不用手工选**：切到 `qwen-image-2.1-UC-Q4_K_M.gguf` 自动带出 `低显存：1MP`，
切到 Turbo GGUF 自动带出 `低显存：0.6MP`，同时换好各自的文本编码器与步数。

### 3.7 MiniMax-H3-Image 双引擎（2026-11-12 新增）

官网：<https://hf-mirror.com/MiniMaxAI/MiniMax-H3-Image>；模型卡要点：
生成与编辑统一在一个 checkpoint、**6 个采样步、无 CFG（CFG=1）、不支持负面提示词**、
参考图按上传顺序称 `<Picture 1> <Picture 2> …`、有效范围约 **4~20 MP**、**16 MP 左右最佳**、
宽高必须是 **32 的倍数**（与本项目 `resolution.calc()` 的 `UNIT=32` 一致）。

**本机所需 3 个模型文件**（都在 `C://AI//ComfyUI_Common//models//`，已通过 ComfyUI
`/object_info` 只读核对可见）：

| 用途 | 相对路径 | ComfyUI 节点 |
|---|---|---|
| DiT | `diffusion_models/minimax_h3_image_pruned_int8_convrot.safetensors` | `UNETLoader` |
| Text Encoder | `text_encoders/minimax_h3/qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | `CLIPLoader`，**`type = minimax`** |
| VAE | `vae/minimax_h3_image_vae_fp16.safetensors` | `VAELoader` |

节点 `MiniMaxH3ImageConditioning` / `ConditioningZeroOut` 是 **ComfyUI 核心内置**
（`comfy_extras/nodes_minimax_h3.py`），**不需要安装任何插件**；官方 UI 模板在
`C://AI//ComfyUI_Common//workflows//H3-Image//`，本项目不导入它，只按同样结构动态生成 API 工作流。

**档位与联动**（`resolution.py` 的 `TIERS` + `config.py` 的 `ENGINE_PRESETS`）：

| 档位 | 2:3 下实际尺寸 | 引擎 |
|---|---|---|
| `H3：16MP` | 3264 × 4896（15.98 MP） | MiniMax-H3-Image |
| `H3：18MP` | 3456 × 5184（17.92 MP） | MiniMax-H3-Image |
| `H3：20MP` | 3648 × 5472（19.96 MP） | MiniMax-H3-Image |
| 其余 7 档（9.4 MP 及以下） | 同原表 | Qwen-Image 2.1（**沿用原默认值**） |

选到这三档会自动套用 H3 三件套、6 步、CFG 1，并重建提示词；切回其它档位恢复 Qwen
默认三件套与 25 步。启动默认值、原有档位尺寸与 Qwen 的 OOM 降档链都**没有变化**。
H3 的降档只在 20 → 18 → 16 MP 内进行，避免重试时把模型和提示词语种悄悄换掉。
`参考图边长` 输入框在 H3 模式下禁用（H3 由内置节点自行缩放参考图）。

**提示词规范**（`h3_workflow.py` 的 `make_h3_prompt()`，参考 WorkBuddy
`h3-image-prompt-writing` 技能的 edit 指南）：

* 一整段**详细英文整图描述**，不用中文、不列点、不写编辑指令句。
* 结构固定为「源内容定义 → 目标图总览 → 各 `<Subject N>` 的关系 → 变化与新增细节」；
  参考图一律用 `<Picture N>`，与上传顺序（人物 → 服装 → 姿态）严格一致。
* **姿态部分直接用 `_metadata.csv` 的「姿态描述_英文」列**（同一姿态 5 个角度各有一行），
  该列已含画幅、躯体、手臂手指、腿脚、脸部朝向与镜头方向；缺列时降级为英文通用句。
  服装库关键词是中文，按 H3 规范不写入英文提示词，服装内容由 `<Picture 2>` 本身定义。
* H3 不支持负面提示词；需要排除文字 / 水印时写在正文里（`No lettering, text or
  watermarks appear.`），`make_negative()` 的结果只传给 Qwen。
* 「保持原图背景」在 H3 下把背景与光线定义为一个 `<Subject N>` 并标记
  `is fully preserved`；「纯白背景」「透明背景」分别改用 `BG_WHITE_EN` /
  `BG_TRANSPARENT_EN` 的英文背景句。H3 不支持负面提示词，三种背景都写在正文里。
* 全裸模式改用中性的英文叙述（`shown without clothing`），并加入身体特征描述：
  `slim, hourglass figure with a narrow waist and a full bust, rosy nipples, smooth bare skin, 
  and sparse pubic hair`。不携带 Qwen 侧的 `completed_nude,...`
  标签串——H3 是自然语言模型，标签串不符合它的提示词规范。

**采样与工作流**：`steps=6`、`cfg=1`、euler / simple；因为无 CFG，官方模板用
`ConditioningZeroOut(positive)` 作为 `KSampler.negative`，本项目照此实现。
`MiniMaxH3ImageConditioning` 同时输出 positive conditioning 与目标尺寸的空白 latent，
因此不需要 `EmptyLatentImage` / `QwenImage21Cache`。参考图走该节点的 Autogrow
动态输入 `images.image_1` / `_2` / `_3`（前缀 `image_`、最多 100 槽），与官方
UI 模板 `minimax-h3-image-edit.json` 里的输入名逐字一致；`image_1` 是被编辑的人物图。
API 样例见 `workflows/api_workflow_h3_image_example.json`。

> 官网给出的 16 MP 常见尺寸是固定表（如 2:3 = 3360×5024）；本项目按用户选的画幅比例
> 用 MP 预算换算，宽高严格等于比例且为 32 的倍数，因此实际像素数会略偏离标称值
> （与原有 Qwen 档位同一套 `calc()` 行为，例如 9:16 下 20 MP 档约为 21.2 MP）。
> 16 MP 是官方推荐值；20 MP 属上限，显存不足会自动降档。

---

## 4. 插件：GGUF 基模需要 ComfyUI-GGUF

选默认基模 `qwen-image-2.1-UC-int8_convrot.safetensors` 时，App 用到的节点
**全部是 ComfyUI 核心内置节点**，不依赖任何插件：

| 节点 | 归属模块 |
|---|---|
| `UNETLoader` / `CLIPLoader` / `VAELoader` / `LoadImage` | `nodes`（核心） |
| `EmptyLatentImage` / `KSampler` / `VAEDecode` / `SaveImage` | `nodes`（核心） |
| `TextEncodeQwenImage21` / `QwenImage21Cache` | `comfy_extras.nodes_qwen`（核心扩展） |

选任意 `*.gguf` 基模（`qwen-image-2.1-UC-Q4_K_M.gguf` 或 `qwen-image-2.1-turbo-Q4_K_M.gguf`）时，
节点 `1` 换成插件节点 `UnetLoaderGGUF`（只收 `unet_name`，没有 `weight_dtype`），
此时**必须安装** [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)。本机已装；插件把
`unet_gguf` 映射到 `diffusion_models` 与 `unet` 两个目录，所以 GGUF 放在
`models/diffusion_models/` 即可（本机两个文件都已在该目录）。

**升级 ComfyUI 到 ≥ v0.37.0 仍比装插件更重要**，但 GGUF 这条路必须有 GGUF 插件。

> **GGUF 文件本身还必须带 `general.architecture = qwen_image21` 元数据。**
> 少数社区量化包（例如本机最初的 `qwen-image-2.1-turbo-Q4_K_M.gguf`）由旧转换脚本生成，
> `kv_count = 0`、没有这个字段，插件会退回 sd.cpp 兼容模式并抛
> `This model is not currently supported - (Unknown model architecture!)`。
> 排查与修复见第 8 节的 `fix_gguf_metadata.py`。

### 可选插件下载地址

| 插件 | 用途 | 地址 |
|---|---|---|
| ComfyUI 本体 | 必需，但这是程序本体不是插件 | <https://github.com/comfyanonymous/ComfyUI> |
| ComfyUI-Manager | 更新 ComfyUI、一键安装缺失节点 | <https://github.com/Comfy-Org/ComfyUI-Manager> |
| ComfyUI-GGUF | **选 GGUF 基模时必需** | <https://github.com/city96/ComfyUI-GGUF>；Qwen-Image 2.1 需支持分支 <https://github.com/leejet/ComfyUI-GGUF> |
| Qwen-Image-2.1 Prompt Enhancer | 仅运行"提示词增强"工作流时需要 | <https://github.com/benjiyaya/ComfyUI-Qwen-Image-2.1-Prompt-Enhancer> |

---

## 5. 工作流：`workflows/` 目录

**运行 App 不需要导入任何工作流文件** —— `workflow.py` 每次按所选模式动态生成 API 格式 JSON。
ComfyUI 支持两种 JSON 格式，容易混淆：

- **UI 格式**（`nodes` / `links` / `definitions`）：从 ComfyUI 界面「保存」出来的，拖进画布可用，
  **不能直接 POST 给 `/prompt`**。
- **API 格式**（`{"节点ID": {"class_type": ..., "inputs": ...}}`）：App 用这种。

本项目 `workflows/` 里放了四份 API 格式样例（三份 Qwen 基模 + 一份 H3-Image，可直接 POST `/prompt`，
需先把 3 张参考图上传进 ComfyUI 的 `input/`；两份 GGUF 版还需装好 ComfyUI-GGUF 插件）：

| 文件 | 基模 / 工作流差异 | 说明 |
|---|---|---|
| `api_workflow_example.json` | `qwen-image-2.1-UC-int8_convrot.safetensors` | 节点 `1` = `UNETLoader`（带 `weight_dtype`），text encoder = heretic，steps 25，1344×1792，seed 固定 |
| `api_workflow_uc_q4_gguf_example.json` | `qwen-image-2.1-UC-Q4_K_M.gguf` | 节点 `1` = `UnetLoaderGGUF`（只有 `unet_name`），text encoder = `qwen3vl_8b_int8_convrot.safetensors`，steps 25 |
| `api_workflow_turbo_gguf_example.json` | `qwen-image-2.1-turbo-Q4_K_M.gguf` | 节点 `1` = `UnetLoaderGGUF`，text encoder = `qwen3vl_8b_w4a8.safetensors`，steps 8 |
| `api_workflow_h3_image_example.json` | `minimax_h3_image_pruned_int8_convrot.safetensors` | 节点 `20` = `MiniMaxH3ImageConditioning`、节点 `33` = `ConditioningZeroOut`，`type=minimax`、steps 6 / CFG 1，英文单段落提示词用 `<Picture N>`，3264×4896 |

**三份 Qwen 样例的差异只可能出现在节点 `1`（loader）、text encoder 文件名与步数这三处**
（UC int8 与 UC-Q4 同为 25 步，节点 `30` 也相同），其余节点完全一致；
App 里由 `workflow.py build()` 按 `.gguf` 后缀自动选择 loader，切换基模时套用推荐组合。

### 保持原姿势：锁定原大小 / 原位置 / 原姿势 / 原表情

姿态页勾选「不换姿势 · 保持原姿势」（即没有姿态参考图）时，除了保持姿势，
**还必须保持人物在原图中的大小、画面位置与面部表情**。这四项由提示词统一约束
（桌面版 `workflow.py` / `h3_workflow.py`，安卓版 `Prompt.kt` / `H3Prompt.kt` 逐字对应）：

- **`keep_pose_line()`**（Qwen 中文）：明确写「人物不放大、不缩小、不平移、不重新构图、
  不裁切，头部、手脚及身体各部位到画幅边缘的距离都与原图一致」，并锁定四肢位置、
  手指状态、身体朝向、头部角度、镜头角度，以及**面部表情、眼神与视线方向、眉眼状态、
  嘴型与所有微表情**。H3 侧对应 `KEEP_POSE_RELATION_EN` 单段落英文叙述。
- **构图句换成 `SCENE_TAIL_KEEP_POSE`**：原来的 `根据输出画幅合理构图，人物完整入画、
  不裁切头脚` 会主动要求模型重新摆位缩放人物，半身 / 近景原图还会被强行拉成全身，
  与「保持原大小、原位置」直接冲突。保持原姿势时整句改为「保持<image1> 的原始取景与构图，
  人物在画面中的大小、位置与透视关系按原图等比延续，不因输出画幅重新构图」；
  H3 侧同时把画幅描述从 `full-length / upper-body portrait` 降级为 `portrait`，
  构图细节句改为 `KEEP_POSE_FRAMING_EN`。
- **负面词**（仅 Qwen 有）：`NEGATIVE_KEEP_POSE` 追加「人物变大或变小，人物位置偏移，
  重新构图，裁切头脚，面部表情改变，眼神或嘴型变化」。H3 不支持负面词。
- **适用范围**：只换装 / 双保持去背 / 全裸且保持原姿势，所有 `pose` 为空的分支
  都走这套约束；有姿态参考图时提示词完全不变。
- 「保持原图背景」的幂等替换 `apply_keep_background()` 同时兼容默认版与保持原姿势版的
  构图整句，替换后四项约束仍由 `keep_pose_line()` 独立承担，不会丢失。

> 提示：输出画幅比例与原图差异越大，模型越难维持等比取景；保持原姿势时建议把分辨率
> 档位的宽高比选得与原图一致。

### 双保持「去背」模式（生成后抠成透明 PNG）

### 「背景」下拉（三种背景模式）

左侧三个 tab 之后、安卓版「4.生成」页顶部固定条，都有一个**背景下拉框**，三选一，
**默认「保持原图背景」**，且**选择会自动保存**：桌面版写 `user_prefs.json`
（不覆盖用户手工维护的 `config.json`），安卓版写 `SharedPreferences` 的 `bgMode`，
下次打开应用直接沿用上次选中的项。

| 选项 | 提示词 | 工作流 | 输出 |
| --- | --- | --- | --- |
| 保持原图背景（默认） | 末尾整句 `保持<image1> 的背景、光线不变。`，H3 把背景与光线定义为一个 `<Subject N>` 并标记 `is fully preserved` | 不变（普通生成） | 不透明 PNG |
| 纯白背景 | 背景替换为纯净均匀的纯白摄影棚背景，负面词抑制背景杂物与阴影 | 不变（普通生成） | 白底不透明 PNG |
| 透明背景 | 背景压成纯净均匀的单一浅色平涂色，便于精确抠图 | `VAEDecode → SplitImageWithAlpha(41) → BiRefNetRMBG(40) → SaveImage(32)` | **RGBA 透明 PNG** |

要点：

- 三种背景对**所有生成模式**都生效（只换装 / 只换姿势 / 换装+换姿势 / 全裸 /
  双保持「原样保留」），不再与任何素材选项互斥；模式标签会追加当前背景名。
- 「双保持」＝服装页勾「保持原服装」**且**姿态页勾「保持原姿势」，参考图只有人物
  原图 1 张，`_plain_mode()` / `plainMode()` 识别它；此时 Qwen 走
  `make_plain_prompt(bg_mode)` / `NEGATIVE_PLAIN`，H3 走
  `make_h3_plain_prompt(bg_mode)`（英文单段落、无负面词）。**背景由下拉决定**，
  不再固定去背；想拿透明 PNG 就把下拉选成「透明背景」。
- 纯白 / 透明两种模式的 Qwen 负面词统一经 `with_bg_negative()` 追加
  `NEGATIVE_BG_CLUTTER`；H3 不支持负面提示词，全部写在正文里。
- `BiRefNetRMBG` 来自 ComfyUI-RMBG 插件，默认模型 `BiRefNet_lite`（177 MB，
  处理分辨率 1024）。权重放在 `ComfyUI/models/RMBG/BiRefNet/`（`birefnet_lite.py`、
  `BiRefNet_config.py`、`BiRefNet_lite.safetensors`、`config.json`），
  **服务端一份即可，桌面版与安卓版共用**。换更大的模型改 `config.py` 的 `RMBG_MODEL`。
- 插件的 `process_image()` 用 `params["mask_blur"]` 直接索引 optional 参数，
  所以 API 格式下 `mask_blur / mask_offset / invert_output / background` 必须显式传，
  统一由 `config.rmbg_inputs()` 生成（安卓版是 `Rmbg.inputs()`）。
- `SplitImageWithAlpha` 不能省：Qwen 的 VAE 解出 4 通道，BiRefNet 只接受 3 通道，
  否则报 `tensor a (4) must match tensor b (3)`；该节点对 3 通道输入原样返回。
- 双保持同样属于「保持原姿势」，因此也套用上一节的四项锁定：构图句用
  `STRIP_BG_TAIL_KEEP_POSE`（中文）/ `KEEP_POSE_FRAMING_EN`（H3），
  不再写「根据输出画幅合理构图」或指定 full-length / half-body 画幅。

### 官方工作流模板下载地址

模板仓库：<https://github.com/Comfy-Org/workflow_templates/tree/main/templates>
也可以在 ComfyUI 里用 **Workflow → Browse Templates → 搜 "Qwen Image 2.1"** 加载。

```
https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_qwen_image_2_1_image_edit.json
https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_qwen_image_2_1_t2i.json
https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_qwen_image_2_1_background_removal.json
```

---

## 6. 项目目录结构

```
PoseWearStudio/
├─ README.MD                 本说明
├─ run.bat                   启动入口（双击）
├─ config.json               用户配置（覆盖 config.py 默认值）
├─ config.py                 默认配置与路径解析
├─ app.py                    PyQt6 界面
├─ catalog.py                素材库索引（读 _metadata.csv）
├─ thumbs.py                 缩略图缓存与后台生成
├─ workflow.py               ★ 动态构造 API 格式工作流
├─ comfy_client.py           ComfyUI HTTP API 客户端
├─ generator.py              后台生成线程（上传/排队/轮询/落盘/OOM 降档）
├─ resolution.py             比例 → 精确宽高（32 倍数）
├─ test_pipeline.py          端到端自检脚本
├─ fix_gguf_metadata.py      修复缺 general.architecture 的 GGUF 文件（见第 8 节）
├─ workflows/                ★ 工作流参考与备份（见第 5 节）
├─ 服装库/ 姿态库/           项目内素材库（含 _metadata.csv）
├─ cache/thumbs/             缩略图缓存（可删，会自动重建）
└─ output/                  生成结果
```

---

## 7. 启动与验证

1. 启动 ComfyUI，确认 `http://127.0.0.1:8188/system_stats` 能返回 JSON。
2. 双击 `run.bat`。**换机器时**需改 `run.bat` 里这两行的路径：

   ```bat
   set PY="C:\AI\ComfyUI-aki-v3\python\python.exe"
   set COMFY_DIR="C:\AI\ComfyUI-aki-v3\ComfyUI"
   ```

   `run.bat` 会检测 8188 端口，没开就自动拉起 ComfyUI；文件本身必须保持 **CRLF 行尾 + 纯 ASCII**。
3. 界面顶部显示「ComfyUI 已连接 · xx GB 显存可用」即就绪。

**左侧「① 人物照片」**：选图或拖放后，图片下方会显示原图分辨率（`宽 × 高`、MP、
宽高比）与最接近的 9 种画幅比例之一（附偏差 %），并给出输出比例建议。判定在
`resolution.py` 的 `nearest_ratio()`：以 `|ln(原图宽高比 / 候选比例)|` 为距离，
横幅 / 竖幅互为倒数时判定对称；文案由 `photo_info_text()` 生成，安卓版逐字一致。

**右侧分栏**：默认「生成」tab 的最上方是「提示词」控件组（在原来 180px 基础上，
按当前字体行高再增加 2 行可见高度，带常显的垂直滚动条，内容更长时直接滚动查看）；
下方左侧是「输出画幅比例」：9 个比例按钮竖向一列（默认选中 `2:3`），
组底部备注只显示最终分辨率，形如 `1280:1920`，不再显示比例键、px 与 MP；
「打开输出目录」「另存为」两个按钮也放在这一列、比例组的下方。
右侧「生成结果」只保留预览图与结果信息，预览区因此可以用满剩余高度。
不常调整的「生成分辨率」（含「低显存：1MP」「低显存：0.6MP」两档，以及
`H3：16/18/20MP` 三档，见 3.7 节）与「生成参数」
（步数 / CFG / 种子 / 参考图边长 + 基模、Text Encoder、VAE 三个模型下拉）在「分辨率与参数」tab。
切换基模会自动套用推荐 text encoder、步数与分辨率档位三项，详见 3.5 节。
「开始生成」「中断当前任务」、进度与状态固定在右侧底栏，两个 tab 下都可见。
**应用启动即窗口最大化**（`main()` 用 `showMaximized()`；点「还原」回到 1500×950），
默认尺寸下无需滚动即可看全全部常用控件。

**左侧三个 tab 之后的「保持原图背景」选项**：勾选后，自动生成提示词末尾的整句

**左侧三个 tab 之后的「背景下拉框」**：三选一（保持原图背景 / 纯白背景 / 透明背景），
默认「保持原图背景」，选择写入 `user_prefs.json`，下次启动自动恢复。

三种背景的提示词整句分别由 `workflow.py` 的 `bg_scene_tail()` / `BG_PARA_WHITE` /
`BG_PARA_TRANSPARENT` 与 `h3_workflow.py` 的 `bg_en()` / `BG_WHITE_EN` /
`BG_TRANSPARENT_EN` 生成（安卓版 `Prompt.kt` / `H3Prompt.kt` 逐字对应），
不再是「勾选后做一次幂等整句替换」。默认「保持原图背景」时末尾整句为

> `保持<image1> 的背景、光线不变。`

若手工改过提示词，切换背景下拉、重新点选素材或切换任一选项即可按当前状态重建。
右侧模式标签会追加当前背景名。
**姿态库「上半身单人」系列的半身构图**（2026-11-10 与安卓版同步）：该系列是半身 / 胸像参考图，
不能要求「人物完整入画、不裁切头脚」。只要「③ 选择姿态」的系列下拉选到「上半身单人」，
或选中的姿态图属于该系列（CSV「系统」列），提示词里的构图句就会自动换成

> `半身取景，头部与上半身完整入画、不裁切头部与肩膀，腿部不必入画`

整句其余部分（光线、皮肤质感、画质、无水印）保持不变；系列下拉一变就立即重建提示词，
右侧模式标签追加「· 半身构图」。判定优先级与安卓版一致：**选中姿态图 > 系列下拉**；
勾选「不换姿势 · 保持原姿势」或「全裸 · 无服装」且没有姿态参考图时不按系列推断，
改用「保持原取景」专用构图句 `SCENE_TAIL_KEEP_POSE`（见上节），不再写全身 / 半身要求。
勾选「保持原图背景」时，半身模式替换成 `保持<image1> 的背景、光线不变。` 之后会补回半身构图句，
不会把构图信息一起丢掉（替换仍幂等）；全裸模式同样生效。保持原姿势版的构图整句也能被同一函数
幂等替换，替换后大小 / 位置 / 表情的约束句仍保留。
常量 `UPPER_BODY_SYSTEM` / `FRAME_FULL` / `FRAME_UPPER` 定义在 `workflow.py`，
与安卓版 `Prompt.kt` 逐字对应。`test_pipeline.py` 不经过界面，默认仍是全身构图句，
需要半身时给 `make_prompt()` 传 `upper_body=True` 即可。

**姿态描述驱动的参考句**（2026-11-11 与安卓版同步）：姿态参考句统一前缀为
`让她的身体姿势、四肢位置、脸部朝向、身体朝向与镜头角度完全参照 <imageN>：`，
冒号后的内容**全部来自** `姿态库/_metadata.csv` 的「姿态描述_中文」列——每段描述已包含
画幅、躯体姿势、手臂手掌手指、腿部与脚、脸部朝向、镜头方向，且同一姿态的 5 个角度各有
独立描述。`catalog.py` 把该列读进 `Pose.description`，`workflow.py` 的
`pose_reference_line()` 生成整句，`make_prompt()` 与全裸模式 `app.py._nude_prompt()`
共用它（安卓版 `Prompt.kt` 逐字对应）。全裸模式不再使用 `completed_nude,...` 标签串，
改为中文自然语言：「纤细沙漏型身材，窄腰，丰满的胸部，粉嫩乳头，光滑裸露的肌肤，阴部有稀疏的阴毛」。

已**移除**按「角度」列追加的 `，XX视角` 与 `脸部朝下。` 等短句（`FACE_DIRECTION` 双端删除），
避免与描述列里已有的脸部朝向、镜头方向重复或冲突。`<imageN>` 按上传顺序动态分配：
服装 + 姿态为 `<image3>`，只选姿态 / 全裸 + 姿态为 `<image2>`。
若素材库是旧版 CSV（缺「姿态描述_中文」列），会降级为「姿态名 + 角度视角。」并在启动时
给出提示；请把项目内更新后的 `_metadata.csv` 同步到素材库目录。
「保持原图背景」只替换末尾的构图/背景整句，姿态参考句与「保持原姿势」的四项约束句都不受影响。

命令行自检（不依赖界面，验证「上传 → 出图 → 落盘」全链路）：

```bash
cd C:\Users\excel\WorkBuddy\Claw\PoseWearStudio
C:\AI\ComfyUI-aki-v3\python\python.exe test_pipeline.py 1:1 1.0 both
# 可选第三参数：both（默认）/ costume（只换装）/ pose（只换姿势）
```

想绕开 App 直接验证工作流，可把 `workflows/api_workflow_example.json` 里的 `prompt` 字段
POST 到 `http://127.0.0.1:8188/prompt`。注意需先把 3 张参考图按 JSON 中 `LoadImage`
节点 `image` 字段的名字（`pws_person_example.png` 等）放进 ComfyUI 的 `input/` 目录
（或用 `/upload/image` 上传）。

```bash
C:\AI\ComfyUI-aki-v3\python\python.exe -c "import json,urllib.request; d=json.load(open('workflows/api_workflow_example.json',encoding='utf-8')); op=urllib.request.build_opener(urllib.request.ProxyHandler({})); r=op.open(urllib.request.Request('http://127.0.0.1:8188/prompt', data=json.dumps({'prompt':d['prompt']}).encode(), headers={'Content-Type':'application/json'})); print(r.read().decode())"
```

（本机 `curl` 走代理访问 localhost 会返回 502，所以用 `ProxyHandler({})` 绕过代理。）

---

## 8. 常见故障

| 现象 | 原因与处理 |
|---|---|
| `TextEncodeQwenImage21` / `QwenImage21Cache` 节点找不到 | ComfyUI < v0.37.0，升级后**完整重启** |
| 模型下拉列表是空的 | 文件放错目录 / 文件名不符 / 放完后没重启 ComfyUI |
| VAE 报通道数不匹配 | 误用了 Qwen-Image 1.0 的 3 通道 VAE，换 `qwen_image_2.1_vae_bf16.safetensors` |
| 生成时显存不足 | `config.json` 调小 `megapixels`；或加 `"cache_device": "cpu"`、`"cache_dtype": "int8"`；App 本身也会自动逐档降分辨率重试 |
| 界面显示「ComfyUI 未连接」 | 检查 8188 端口、`comfy_url`；本机代理会拦 localhost，客户端已设 `trust_env=False` |
| 提示词报 `<imageN>` 引用越界 | 手改提示词后张数与所选模式不符，重新点选素材或切换任一选项即可重建提示词 |
| 素材列表为空 | `config.json` 的 `library_root` 指错；默认 `"."` 即项目根目录 |
| 界面中文变方框 | 系统缺中文字体，App 已内置 `Microsoft YaHei` / `Noto Sans SC` / `DengXian` 回退 |
| 操作后程序突然退出 | 已修复；异常现在写入 `cache/error.log` 并弹窗提示，不再 abort |
| 选 Turbo GGUF 生成失败：`execution_error` / `UnetLoaderGGUF` / `This model is not currently supported - (Unknown model architecture!)` | 该 GGUF 缺 `general.architecture`，见下方 8.1 |

### 8.1 GGUF 报 `Unknown model architecture`（2026-11-10 实测修复）

**症状**：App 选 `qwen-image-2.1-turbo-Q4_K_M.gguf` 后返回带 `execution_error`、
`node_type = UnetLoaderGGUF` 的错误串。

**根因**（与 App 代码无关，问题在模型文件）：该文件 `kv_count = 0`，没有
`general.architecture`，且 297 个张量名还带 `model.diffusion_model.` 前缀 —— 是旧
转换脚本的产物。ComfyUI-GGUF 的 `loader.py` 见 `arch_str is None` 就进入 sd.cpp
兼容模式，转去调 `tools/convert.py` 的 `detect_arch()`；那份旧 `arch_list` 只列了
flux / sd3 / wan / sdxl 等，**没有 `qwen_image21`**，于是断言
`Unknown model architecture!`，`loader.py:105` 包装成上面那句报错。
同目录的 `qwen-image-2.1-UC-Q4_K_M.gguf` / `UC-Q8_0.gguf` 都带
`general.architecture = qwen_image21`，所以能正常加载。

**修复**：项目根目录 `fix_gguf_metadata.py` 只改写 GGUF 头部 —— 插入
`general.architecture` / `quantization_version` / `file_type` 三个 KV 并重新对齐
padding，张量 shape / type / offset 与全部量化字节原样保留，**不重新量化、不改文件名**：

```bash
python fix_gguf_metadata.py "C:/AI/ComfyUI-aki-v3/ComfyUI/models/diffusion_models/qwen-image-2.1-turbo-Q4_K_M.gguf" --plugin-loader "C:/AI/ComfyUI-aki-v3/ComfyUI/custom_nodes/ComfyUI-GGUF/loader.py" --apply
```

不加 `--apply` 只生成 `.fixed` 副本并全量校验；`--apply` 会把原文件备份成 `.gguf.bak`
再替换。因为文件名不变，**ComfyUI 无需重启**，直接重新点「开始生成」。

本机 2026-11-10 已修复：`data_offset 29728 → 29856`，4,050,886,656 字节数据区
sha256 与原文件完全一致；离屏调用 `gguf_sd_loader()` 返回
`arch_str = qwen_image21`、297 张量，state_dict 的 key 集合与 UC-Q4 逐项一致。
备份留在 `models/diffusion_models/qwen-image-2.1-turbo-Q4_K_M.gguf.bak`（约 3.8 GB），
确认新版可用后可自行删除。

---

## 9. 许可与合规

- Qwen-Image 2.1 采用 **Qwen Research License Agreement**，授权范围限定于**非商业研究/评估**，
  商业使用需另向 Qwen 申请许可；官方还要求在衍生产品文档中标注 "Built with Qwen"。
  使用前请自行阅读完整许可：<https://huggingface.co/Comfy-Org/Qwen-Image-2.1>。
- 本机默认的两个社区权重为破限 / 去审查版本，请自行评估其来源、许可与合规风险；
  若要干净可复现的安装，用第 3.1 节的官方三件套。
- 界面已注明：**仅限本人或已获授权的成年人肖像**，请勿上传未成年人照片。

---

## 附：本机实测环境（2026-11-09）

| 项 | 值 |
|---|---|
| ComfyUI | 0.42.5（节点均为内置，零插件依赖） |
| Python / torch | 3.13.11 / 2.9.1+cu130 |
| GPU | RTX 5090 Laptop 24 GB |
| 模型 | 社区 UC-int8 + Heretic-int8convrot + 官方 VAE，合计 18.9 GB |
| 采样 | steps 25 / CFG 1.0 / euler / simple / ref_resolution 1024 |
| 直出上限 | 9.4 MP（16:9 = 4096×2304）；当前 `config.json` 设为 2.4 MP 以加快出图 |
| 参考出图耗时 | 1.0 MP ≈ 25 s；2.4 MP ≈ 36 s；9.4 MP ≈ 176 s |
