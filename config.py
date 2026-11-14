# -*- coding: utf-8 -*-
"""PoseWear Studio 全局配置。修改 config.json 可覆盖这里的默认值。

素材库随项目走：默认读取项目目录下的「服装库」「姿态库」两个子目录。
library_root / output_dir / cache_dir 都支持相对路径，一律相对本文件所在
目录（BASE）解析，因此整个项目搬到任何位置都能直接运行。
如需临时改用网络盘或其他位置的素材，把 library_root 写成绝对路径即可。

双引擎：默认仍是 Qwen-Image 2.1（沿用原来的默认值）；像素档位选到
16 / 18 / 20 MP 时自动切换为 MiniMax-H3-Image，并套用它的三件套、
6 步与 CFG 1。引擎预设集中在 ENGINE_PRESETS，界面与生成器共用。
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "comfy_url": "http://127.0.0.1:8188",

    # "." 表示两个素材库直接放在项目根目录下；也可填 "assets" 之类的子目录
    "library_root": ".",
    "output_dir": "output",
    "cache_dir": "cache",

    # 本机 Qwen-Image 2.1 三件套（ComfyUI models 下的相对名）
    "unet": "qwen-image-2.1-UC-int8_convrot.safetensors",
    "clip": r"qwen_image_2.1\qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors",
    "vae": "qwen_image_2.1_vae_bf16.safetensors",
    "clip_type": "qwen_image",
    "weight_dtype": "default",

    # 采样参数（与本机官方 Qwen-Image-2.1_image_edit 工作流一致）
    "steps": 25,
    "cfg": 1.0,
    "sampler": "euler",
    "scheduler": "simple",
    "ref_resolution": 1024,
    "cache_device": "auto",
    "cache_dtype": "default",

    # 输出像素预算（百万像素），程序按比例换算成 32 倍数的精确宽高
    "megapixels": 9.4,

    # 素材库分类白名单（由 config.py / config.json 共同决定）
    "costume_categories": ["春装", "夏装", "秋装", "冬装", "泳装", "派对礼服","内衣","性感装"],
    "pose_systems": ["全身单人-标准系", "上半身单人","全身单人-性感系", "双人互动"],
    "pose_categories_excluded": [],

    "page_size": 60,
    "request_timeout": 20,
    "generation_timeout": 1200,
    # 生成页「背景」下拉框的选项，默认「保持原图背景」；运行时改动写 user_prefs.json
    "bg_mode": "keep",
}

# ---------- MiniMax-H3-Image 三件套 ----------
# 与本机官方 ComfyUI「MiniMax H3 Image Edit」模板逐字一致：
#   UNETLoader  -> models/diffusion_models/minimax_h3_image_pruned_int8_convrot.safetensors
#   CLIPLoader  -> models/text_encoders/minimax_h3/qwen3vl_32b_...int8_convrot.safetensors
#                  type = "minimax"（不是 qwen_image）
#   VAELoader   -> models/vae/minimax_h3_image_vae_fp16.safetensors
# 官网：6 个采样步、无 classifier-free guidance（CFG=1）、不支持负面提示词，
# 有效工作范围约 4~20 MP、16 MP 左右效果最佳。
H3_UNET = "minimax_h3_image_pruned_int8_convrot.safetensors"
H3_CLIP = r"minimax_h3\qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
H3_VAE = "minimax_h3_image_vae_fp16.safetensors"
H3_CLIP_LABEL = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
H3_UNET_LABEL = H3_UNET
H3_VAE_LABEL = H3_VAE
H3_CLIP_TYPE = "minimax"
H3_STEPS = 6
H3_CFG = 1.0

# ---------- 双保持「去背」模式 ----------
# 服装页「保持原服装」+ 姿态页「保持原姿势」同时勾选 = 什么都不换，
# 生成图再经 ComfyUI-RMBG 的 BiRefNetRMBG 抠图，输出带 alpha 的透明 PNG。
# 权重放在 ComfyUI/models/RMBG/BiRefNet/，服务端只需一份，桌面版与安卓版共用。
RMBG_MODEL = "BiRefNet_lite"


# ---------- 生成页「背景」下拉（桌面版 / 安卓版取值一致） ----------
BG_MODES = ("keep", "white", "transparent")
BG_MODE_LABELS = {
    "keep": "保持原图背景",
    "white": "纯白背景",
    "transparent": "透明背景",
}
DEFAULT_BG_MODE = "keep"
# 界面选择单独存放，不污染用户手工维护的 config.json
PREFS_PATH = os.path.join(BASE, "user_prefs.json")


def normalize_bg_mode(value):
    """非法 / 旧值一律回落为默认「保持原图背景」。"""
    return value if value in BG_MODES else DEFAULT_BG_MODE


def save_pref(key, value):
    """把界面选项写回 user_prefs.json（读-改-写，保留其它键）。"""
    data = {}
    if os.path.isfile(PREFS_PATH):
        try:
            with open(PREFS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    data[key] = value
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print("user_prefs.json 写入失败（本次会话仍生效）:", exc)


def rmbg_inputs(image_link):
    """BiRefNetRMBG 节点的 API 输入（两个引擎的工作流共用）。

    插件 process_image() 用 params["mask_blur"] 这种方式直接索引 optional
    参数而不是 .get()，所以 API 格式下这几个参数必须显式传，否则会抛
    KeyError: 'mask_blur'。background="Alpha" 让第一个输出成为 RGBA
    四通道图，SaveImage 直接落盘就是透明 PNG。
    """
    return {
        "image": image_link,
        "model": RMBG_MODEL,
        "sensitivity": 1.0,
        "mask_blur": 0,
        "mask_offset": 0,
        "invert_output": False,
        "refine_foreground": False,
        "background": "Alpha",
    }


# ---------- 可选模型清单 ----------
# 每项 = (界面显示名, 传给 ComfyUI 的 unet_name / clip_name / vae_name)。
# qwen_image_2.1 / minimax_h3 的 text encoder 都在各自子目录，
# 所以 clip_name 必须带子目录前缀，界面只显示纯文件名。
UNET_MODELS = [
    ("qwen-image-2.1-UC-int8_convrot.safetensors",
     "qwen-image-2.1-UC-int8_convrot.safetensors"),
    ("qwen-image-2.1-UC-Q4_K_M.gguf",
     "qwen-image-2.1-UC-Q4_K_M.gguf"),
    ("qwen-image-2.1-turbo-Q4_K_M.gguf",
     "qwen-image-2.1-turbo-Q4_K_M.gguf"),
    ("[H3] " + H3_UNET_LABEL, H3_UNET),
]
CLIP_MODELS = [
    ("qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors",
     r"qwen_image_2.1\qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors"),
    ("qwen3vl_8b_int8_convrot.safetensors",
     r"qwen_image_2.1\qwen3vl_8b_int8_convrot.safetensors"),
    ("qwen3vl_8b_w4a8.safetensors",
     r"qwen_image_2.1\qwen3vl_8b_w4a8.safetensors"),
    ("[H3] " + H3_CLIP_LABEL, H3_CLIP),
]
VAE_MODELS = [
    ("qwen_image_2.1_vae_bf16.safetensors",
     "qwen_image_2.1_vae_bf16.safetensors"),
    ("[H3] " + H3_VAE_LABEL, H3_VAE),
]

# 切换基模时的推荐组合：
#   (text_encoder 显示名, 默认步数, 生成分辨率档位名, VAE 显示名, CFG)。
# 档位名必须与 resolution.py 的 TIERS 键逐字一致，统一「名称：数值MP」格式
# （全角冒号，数值后无空格）。
# 启动时与每次切换基模时各套用一次；之后手工改的值不会被覆盖，直到下次切换基模。
# 两个 Q4_K_M.gguf 都走 ComfyUI-GGUF 的 UnetLoaderGGUF（workflow.build 按后缀自动判定）。
_QWEN_VAE_LABEL = "qwen_image_2.1_vae_bf16.safetensors"
UNET_DEFAULTS = {
    "qwen-image-2.1-UC-int8_convrot.safetensors":
        ("qwen3-vl-8b-heretic-1.3.0-int8convrot.safetensors", 25,
         "标准：2.4MP", _QWEN_VAE_LABEL, 1.0),
    "qwen-image-2.1-UC-Q4_K_M.gguf":
        ("qwen3vl_8b_int8_convrot.safetensors", 25,
         "低显存：1MP", _QWEN_VAE_LABEL, 1.0),
    "qwen-image-2.1-turbo-Q4_K_M.gguf":
        ("qwen3vl_8b_w4a8.safetensors", 8,
         "低显存：0.6MP", _QWEN_VAE_LABEL, 1.0),
    H3_UNET:
        ("[H3] " + H3_CLIP_LABEL, H3_STEPS, "H3：16MP",
         "[H3] " + H3_VAE_LABEL, H3_CFG),
}

# 按档位切换引擎时套用的一组完整参数。界面的下拉与生成参数都从这里取值。
ENGINE_PRESETS = {
    "qwen": {
        "unet": DEFAULTS["unet"],
        "clip": DEFAULTS["clip"],
        "vae": DEFAULTS["vae"],
        "steps": DEFAULTS["steps"],
        "cfg": DEFAULTS["cfg"],
        "clip_type": DEFAULTS["clip_type"],
        "tier": "标准：2.4MP",
    },
    "h3": {
        "unet": H3_UNET,
        "clip": H3_CLIP,
        "vae": H3_VAE,
        "steps": H3_STEPS,
        "cfg": H3_CFG,
        "clip_type": H3_CLIP_TYPE,
        "tier": "H3：16MP",
    },
}

# CLIPLoader 的 type 由基模决定：H3 三件套必须用 "minimax"。
CLIP_TYPE_BY_UNET = {H3_UNET: H3_CLIP_TYPE}


def clip_type_for(unet, default="qwen_image"):
    """返回该基模对应的 CLIPLoader.type；自定义模型沿用配置值。"""
    return CLIP_TYPE_BY_UNET.get(unet, default)


def _resolve(value):
    """相对路径按项目根目录 BASE 解析为绝对路径；绝对路径原样规范化。"""
    path = os.path.expanduser(os.path.expandvars(str(value)))
    if not os.path.isabs(path):
        path = os.path.join(BASE, path)
    return os.path.normpath(path)


def load():
    cfg = dict(DEFAULTS)
    path = os.path.join(BASE, "config.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as exc:  # 配置坏了也不应阻塞启动
            print("config.json 读取失败，使用默认值:", exc)
    # 界面选项（背景下拉等）自动恢复，覆盖 DEFAULTS 里的默认值
    if os.path.isfile(PREFS_PATH):
        try:
            with open(PREFS_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except Exception as exc:
            print("user_prefs.json 读取失败，使用默认值:", exc)
    cfg["bg_mode"] = normalize_bg_mode(cfg.get("bg_mode"))
    for key in ("library_root", "output_dir", "cache_dir"):
        cfg[key] = _resolve(cfg[key])
    for key in ("output_dir", "cache_dir"):
        os.makedirs(cfg[key], exist_ok=True)
    return cfg


CFG = load()
