# -*- coding: utf-8 -*-
"""按画幅比例 + 像素预算，算出 VAE 友好的最大直出分辨率。

令 w = a * UNIT * u, h = b * UNIT * u（UNIT=32），这样宽高比严格等于 a:b，
且宽高均为 32 的倍数，无需事后裁切或拉伸。Qwen-Image 2.1 的 VAE 与
MiniMax-H3-Image 的 CANVAS_MULTIPLE 都要求 32 的倍数，因此同一个 calc()
可同时服务两个引擎。

引擎由像素档位决定：16 MP 及以上的三档走 MiniMax-H3-Image，其余档位
走 Qwen-Image 2.1（沿用原有的默认档位与降级行为）。
"""
import math
from collections import OrderedDict

RATIOS = OrderedDict([
    ("1:1",  (1, 1)),
    ("2:3",  (2, 3)),
    ("3:4",  (3, 4)),
    ("4:5",  (4, 5)),
    ("9:16", (9, 16)),
    ("4:3",  (4, 3)),
    ("3:2",  (3, 2)),
    ("16:9", (16, 9)),
    ("21:9", (21, 9)),
])

UNIT = 32

# 本机 RTX 5090 Laptop 24GB + Qwen-Image 2.1 int8 的实测档位：
#   9.4 MP = 4096x2304 (16:9) 用时约 176s  ← 实测最大直出
#   7.2 MP = 3584x2016 约 124s
#   5.3 MP = 3072x1728 约 84s
#   2.4 MP = 1344x1792 约 36s
# 末尾两档面向 6 GB 显存的机器（2:3 下约 832x1248 / 640x960）。
#
# MiniMax-H3-Image 官方有效工作范围约 4~20 MP，16 MP 左右效果最好，
# 因此新增 16 / 18 / 20 MP 三档，全部走 H3 引擎（6 步 / CFG 1）。
# 档位名统一为「名称：数值MP」：全角冒号、数值与 MP 之间不留空格。
TIERS = OrderedDict([
    ("H3：20MP", 20.0),
    ("H3：18MP", 18.0),
    ("H3：16MP", 16.0),
    ("极限：9.4MP(4K)", 9.4),
    ("超清：7.2MP", 7.2),
    ("高清：5.3MP", 5.3),
    ("标准：2.4MP", 2.4),
    ("快速：1.5MP", 1.5),
    ("低显存：1MP", 1.0),
    ("低显存：0.6MP", 0.6),
])

# H3 档位的最小像素预算；高于等于此值的档位一律走 MiniMax-H3-Image。
H3_MIN_MP = 16.0
H3_TIERS = frozenset(k for k, v in TIERS.items() if v >= H3_MIN_MP)
QWEN_TIERS = frozenset(k for k, v in TIERS.items() if v < H3_MIN_MP)


def engine_for(megapixels):
    """按像素预算返回引擎名：'h3' 或 'qwen'。"""
    return "h3" if float(megapixels) >= H3_MIN_MP else "qwen"


def engine_for_tier(tier_name):
    """按档位名返回引擎名；未知档位按像素兜底为 qwen。"""
    return engine_for(TIERS.get(tier_name, 0.0))


def calc(ratio_key, megapixels, unit=UNIT):
    """返回 (width, height)；严格满足比例，且为 unit 的倍数。"""
    a, b = RATIOS[ratio_key]
    u = int(round(math.sqrt(megapixels * 1_000_000 / (a * b * unit * unit))))
    u = max(1, u)
    return a * unit * u, b * unit * u


def describe(ratio_key, megapixels):
    w, h = calc(ratio_key, megapixels)
    return w, h, w * h / 1_000_000


# ---------- 原图画幅分析（人物页图片下方显示） ----------

def nearest_ratio(w, h):
    """返回 (最接近的比例键, 相对偏差%)；宽高非法时返回 None。

    距离取 |ln(r / t)|（r = 原图宽高比，t = 候选比例 a/b）：横幅与竖幅
    互为倒数时判定对称，不会系统性地偏向某一侧。平局按 RATIOS 声明顺序取第一个。
    """
    if not w or not h or w <= 0 or h <= 0:
        return None
    r = float(w) / float(h)
    best_key, best_dist = None, float("inf")
    for key, (a, b) in RATIOS.items():
        t = a / b
        d = abs(math.log(r / t))
        if d < best_dist - 1e-12:
            best_key, best_dist = key, d
    a, b = RATIOS[best_key]
    dev = abs(r / (a / b) - 1.0) * 100.0
    return best_key, dev


def photo_info_text(w, h):
    """人物照片下方的两行说明；安卓版 Resolution.photoInfoText() 与之逐字一致。"""
    near = nearest_ratio(w, h)
    if near is None:
        return "分辨率读取失败，无法显示画幅比例。"
    key, dev = near
    mp = w * h / 1_000_000.0
    r = w / h
    return ("分辨率 {w} × {h}（{mp:.1f} MP）· 宽高比 {r:.3f}\n"
            "最接近画幅比例 {key}（偏差 {dev:.1f}%）· 建议把输出画幅比例设为 {key}"
            ).format(w=w, h=h, mp=mp, r=r, key=key, dev=dev)


def tier_steps(megapixels, engine=None):
    """自动降级顺序：从当前档位（含）往下降到最低档。

    engine 不传时保持旧行为（所有不高于当前预算的档位）。
    传 'h3' 时只在 20/18/16 MP 三档内降，传 'qwen' 时排除 H3 档——
    这样 Qwen 的降级链与新增 H3 档之前逐字一致，也不会在 OOM 时
    把引擎和提示词的语种悄悄换掉。
    """
    vals = [v for v in TIERS.values() if v <= megapixels + 1e-6]
    if engine == "h3":
        vals = [v for v in vals if v >= H3_MIN_MP]
    elif engine == "qwen":
        vals = [v for v in vals if v < H3_MIN_MP]
    if not vals:
        vals = [megapixels]
    return vals


if __name__ == "__main__":
    for r in RATIOS:
        w, h, real = describe(r, 9.4)
        print(f"{r:>5} @9.4MP -> {w:>5} x {h:<5} {real:.2f} MP")
