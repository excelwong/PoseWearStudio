# -*- coding: utf-8 -*-
"""PoseWear Studio 全局配置。修改 config.json 可覆盖这里的默认值。

素材库随项目走：默认读取项目目录下的「服装库」「姿态库」两个子目录。
library_root / output_dir / cache_dir 都支持相对路径，一律相对本文件所在
目录（BASE）解析，因此整个项目搬到任何位置都能直接运行。
如需临时改用网络盘或其他位置的素材，把 library_root 写成绝对路径即可。
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
}


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
    for key in ("library_root", "output_dir", "cache_dir"):
        cfg[key] = _resolve(cfg[key])
    for key in ("output_dir", "cache_dir"):
        os.makedirs(cfg[key], exist_ok=True)
    return cfg


CFG = load()
