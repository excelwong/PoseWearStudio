# -*- coding: utf-8 -*-
"""按画幅比例 + 像素预算，算出 VAE 友好的最大直出分辨率。

令 w = a * UNIT * u, h = b * UNIT * u（UNIT=32，Qwen-Image VAE 安全倍数），
这样宽高比严格等于 a:b，且宽高均为 32 的倍数，无需事后裁切或拉伸。
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
# 显存不足时生成器会自动逐档降级重试。
TIERS = OrderedDict([
    ("极限 9.4 MP (4K)", 9.4),
    ("超清 7.2 MP", 7.2),
    ("高清 5.3 MP", 5.3),
    ("标准 2.4 MP", 2.4),
    ("快速 1.5 MP", 1.5),
])


def calc(ratio_key, megapixels, unit=UNIT):
    """返回 (width, height)；严格满足比例，且为 unit 的倍数。"""
    a, b = RATIOS[ratio_key]
    u = int(round(math.sqrt(megapixels * 1_000_000 / (a * b * unit * unit))))
    u = max(1, u)
    return a * unit * u, b * unit * u


def describe(ratio_key, megapixels):
    w, h = calc(ratio_key, megapixels)
    return w, h, w * h / 1_000_000


def tier_steps(megapixels):
    """自动降级顺序：从当前档位（含）往下降到最低档。"""
    vals = [v for v in TIERS.values() if v <= megapixels + 1e-6]
    if not vals:
        vals = [megapixels]
    return vals


if __name__ == "__main__":
    for r in RATIOS:
        w, h, real = describe(r, 9.4)
        print(f"{r:>5} @9.4MP -> {w:>5} x {h:<5} {real:.2f} MP")
