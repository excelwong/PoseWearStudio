# PoseWear Studio（衣姿工坊）运行说明

输入一张人物正面照片，选服装、选姿态、选输出比例，用本机 ComfyUI 生成指定画幅的高清写实人像。

> **一句话结论**：要让本 App 正常运行，ComfyUI 侧需要 **1 个足够新的 ComfyUI + 3 个模型文件**，
> **不需要任何第三方插件**，也**不需要导入任何工作流文件**（工作流由 App 用代码动态生成）。
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

## 3. 必需模型（3 个文件）

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

---

## 4. 插件：**零个必需**

App 用到的 10 个节点**全部是 ComfyUI 核心内置节点**，不依赖 `custom_nodes/` 下任何插件。
下表来自 `/object_info` 的 `python_module` 字段实测：

| 节点 | 归属模块 |
|---|---|
| `UNETLoader` / `CLIPLoader` / `VAELoader` / `LoadImage` | `nodes`（核心） |
| `EmptyLatentImage` / `KSampler` / `VAEDecode` / `SaveImage` | `nodes`（核心） |
| `TextEncodeQwenImage21` / `QwenImage21Cache` | `comfy_extras.nodes_qwen`（核心扩展） |

所以：**升级 ComfyUI 到 ≥ v0.37.0，比装插件更重要。** 本机装了 近 30 个插件
（Easy-Use、KJNodes、Impact-Pack、rgthree、1hewNodes、GGUF 等），但 App 一个都不调用。

### 可选插件下载地址（非必需）

| 插件 | 用途 | 地址 |
|---|---|---|
| ComfyUI 本体 | 必需，但这是程序本体不是插件 | <https://github.com/comfyanonymous/ComfyUI> |
| ComfyUI-Manager | 更新 ComfyUI、一键安装缺失节点 | <https://github.com/Comfy-Org/ComfyUI-Manager> |
| ComfyUI-GGUF | **仅**运行 `workflows/` 里的 GGUF 版工作流时需要 | <https://github.com/city96/ComfyUI-GGUF>；Qwen-Image 2.1 需支持分支 <https://github.com/leejet/ComfyUI-GGUF> |
| Qwen-Image-2.1 Prompt Enhancer | **仅**运行"提示词增强"工作流时需要 | <https://github.com/benjiyaya/ComfyUI-Qwen-Image-2.1-Prompt-Enhancer> |

> 本机**未安装** Prompt Enhancer 插件，因此 `workflows/` 里两个"提示词增强"工作流
> 缺少 `QwenImage21_EditPromptRewrite` / `QwenImage21_T2IPromptRewrite` 节点，导入后会显示红框。
> 这与 App 运行无关。

---

## 5. 工作流：`workflows/` 目录

**运行 App 不需要导入任何工作流文件** —— `workflow.py` 每次按所选模式动态生成 API 格式 JSON。
但 ComfyUI 支持两种 JSON 格式，容易混淆：

- **UI 格式**（`nodes` / `links` / `definitions`）：从 ComfyUI 界面「保存」出来的，拖进画布可用，
  **不能直接 POST 给 `/prompt`**。
- **API 格式**（`{"节点ID": {"class_type": ..., "inputs": ...}}`）：App 用这种。

本项目 `workflows/` 里放了 8 个文件：

| 文件 | 格式 | 与 App 的关系 |
|---|---|---|
| `Qwen-Image-2.1_image_edit.json` | UI（含 1 个子图） | ★ **App 节点配置的参考来源**：标准 safetensors 链路，模型选择与 `config.py` 对应 |
| `Qwen-Image_2_1_t2i.json` | UI（含 1 个子图） | 同套模型的文生图参考 |
| `api_workflow_example.json` | **API** | ★ **App 实际提交内容的结构样例**：3 图模式、1344×1792、seed 固定，可直接 POST `/prompt`（需先把 3 张参考图上传进 ComfyUI 的 `input/`） |
| `Qwen-Image-2.1_image_edit_Uncensor_合并版.json` | UI（4 子图） | 可选参考，走 GGUF 链路，需 ComfyUI-GGUF + GGUF 权重 + LoRA |
| `Qwen-Image-2.1_image_edit_Uncensor_合并版_提示词增强.json` | UI（2 子图） | 可选参考，另需 Prompt Enhancer 插件与 PE 模型 |
| `Qwen-Image-2.1_image_edit_Uncensor_展开版.json` | UI | 可选参考，GGUF 链路展开版 |
| `Qwen-Image-2.1_image_nipple_edit_Uncensor_展开版.json` | UI | 可选参考，GGUF 链路展开版 |
| `Qwen-Image_2_1_t2i_提示词增强.json` | UI（1 子图） | 可选参考，另需 Prompt Enhancer 插件与 PE 模型 |

后 5 个是本机原有的社区工作流，仅作备份/参考，**App 运行时不读取**。

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

**右侧分栏**：默认「生成」tab 放输出画幅比例、提示词、生成结果（含「打开输出目录」「另存为」）；
不常调整的「生成分辨率」「生成参数」在「分辨率与参数」tab。
「开始生成」「中断当前任务」、进度与状态固定在右侧底栏，两个 tab 下都可见，
默认窗口尺寸下无需滚动即可看全全部常用控件。

**左侧三个 tab 之后的「保持原图背景」选项**：勾选后，自动生成提示词末尾的整句

> `根据输出画幅合理构图，人物完整入画、不裁切头脚，光线自然柔和，背景简洁干净，真实皮肤质感，高细节、高清晰度，专业人像摄影，无文字无水印。`

会被替换为

> `保持<image1> 的背景、光线不变。`

对所有模式（只换装 / 只换姿势 / 换装+换姿势 / 全裸）都生效，右侧模式标签会追加「· 保持原图背景」；
取消勾选即恢复默认文案。若手工改过提示词，重新点选素材或切换任一选项即可按当前状态重建。
这两段文案定义在 `workflow.py` 的 `SCENE_TAIL` / `SCENE_TAIL_KEEP_BG` 常量里，替换逻辑在
`apply_keep_background()`，是唯一来源。

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
