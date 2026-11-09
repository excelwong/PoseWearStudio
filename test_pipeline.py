# -*- coding: utf-8 -*-
"""端到端管线自检：占位人物图 + 真实服装/姿态参考图 → ComfyUI → 保存出图。

用法: python test_pipeline.py [比例] [百万像素] [模式]
  模式: both（默认，换装+换姿势） / costume（只换装） / pose（只换姿势）
"""
import os
import sys
import time

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CFG                      # noqa: E402
from catalog import Catalog                 # noqa: E402
from comfy_client import ComfyClient, ComfyError, OOMError  # noqa: E402
from workflow import build, make_prompt, make_negative, ref_tags  # noqa: E402
from resolution import describe            # noqa: E402


def make_placeholder(path):
    """画一张中性的正面人像占位图，仅用于验证管线，不含真实人物。"""
    im = Image.new("RGB", (768, 1024), (232, 226, 219))
    d = ImageDraw.Draw(im)
    # 头
    d.ellipse((304, 190, 464, 380), fill=(238, 205, 180), outline=(190, 155, 132), width=3)
    # 头发
    d.pieslice((290, 160, 478, 350), 180, 360, fill=(60, 45, 38))
    # 身体（上衣 + 裙子）
    d.polygon([(270, 400), (498, 400), (530, 700), (238, 700)], fill=(96, 126, 156))
    d.polygon([(238, 700), (530, 700), (566, 900), (202, 900)], fill=(72, 78, 96))
    # 手臂 / 腿
    d.line([(270, 420), (215, 690)], fill=(238, 205, 180), width=34)
    d.line([(498, 420), (553, 690)], fill=(238, 205, 180), width=34)
    d.line([(310, 900), (300, 1010)], fill=(238, 205, 180), width=28)
    d.line([(458, 900), (468, 1010)], fill=(238, 205, 180), width=28)
    im.save(path)


def main():
    ratio = sys.argv[1] if len(sys.argv) > 1 else "3:4"
    mp = float(sys.argv[2]) if len(sys.argv) > 2 else CFG["megapixels"]
    mode = sys.argv[3] if len(sys.argv) > 3 else "both"
    if mode not in ("both", "costume", "pose"):
        raise SystemExit("模式必须是 both / costume / pose")
    has_c = mode in ("both", "costume")
    has_p = mode in ("both", "pose")

    client = ComfyClient(CFG["comfy_url"])
    print("[1/5] ComfyUI 状态:", client.status()["system"]["comfyui_version"])

    cat = Catalog(CFG["library_root"], CFG["costume_categories"],
                  CFG["pose_systems"], CFG["pose_categories_excluded"])
    print("[2/5] 素材:", len(cat.costumes), "件服装 /", len(cat.poses), "张姿态",
          "| 模式:", mode)
    costume = (next((c for c in cat.costumes if c.category == "夏装"), cat.costumes[0])
               if has_c else None)
    pose = (next((p for p in cat.poses if p.angle == "正面"), cat.poses[0])
            if has_p else None)
    if costume:
        print("      服装:", costume.id, costume.keywords)
    if pose:
        print("      姿态:", pose.id, pose.name, pose.angle)

    tmp = os.path.join(CFG["cache_dir"], "_test_person.png")
    make_placeholder(tmp)
    # 顺序必须与 ref_tags 一致：人物 → 服装（可选）→ 姿态（可选）
    specs = [("person", tmp, "pws_test_person.png")]
    if costume:
        specs.append(("costume", costume.path, "pws_test_costume.png"))
    if pose:
        specs.append(("pose", pose.path, "pws_test_pose.png"))
    names = [client.upload(path, name) for _, path, name in specs]
    print("[3/5] 已上传:", names)

    w, h, real_mp = describe(ratio, mp)
    print(f"[4/5] 目标 {ratio} -> {w}x{h} ({real_mp:.2f} MP)")
    tags = ref_tags(has_c, has_p)
    prompt = make_prompt(tags,
                         costume_keywords=costume.keywords if costume else "",
                         pose_name=pose.name if pose else "",
                         pose_angle=pose.angle if pose else "")
    flow, out_id = build(
        refs=names, width=w, height=h, prompt=prompt,
        negative=make_negative(tags),
        steps=CFG["steps"], cfg=CFG["cfg"], sampler=CFG["sampler"],
        scheduler=CFG["scheduler"], unet=CFG["unet"], clip=CFG["clip"],
        vae=CFG["vae"], clip_type=CFG["clip_type"],
        weight_dtype=CFG["weight_dtype"], ref_resolution=CFG["ref_resolution"],
        cache_device=CFG["cache_device"], cache_dtype=CFG["cache_dtype"])

    t0 = time.time()
    pid = client.queue(flow)
    print("      prompt_id =", pid)
    last = [0]

    def tick(elapsed, q):
        if int(elapsed) // 10 > last[0]:
            last[0] = int(elapsed) // 10
            run = len(q.get("queue_running", [])) if q else -1
            pend = len(q.get("queue_pending", [])) if q else -1
            print(f"      ... {elapsed:.0f}s  running={run} pending={pend}")

    entry = client.wait(pid, timeout=CFG["generation_timeout"], on_tick=tick)
    imgs = client.images(entry, out_id)
    if not imgs:
        raise ComfyError("没有输出图片")
    data = client.fetch(imgs[0])
    out = os.path.join(CFG["output_dir"],
                       "_pipeline_test_%s_%s.png" % (ratio.replace(":", "x"), mode))
    with open(out, "wb") as f:
        f.write(data)
    print(f"[5/5] 完成，用时 {time.time()-t0:.1f}s，输出 {out} ({len(data)//1024} KB)")
    return out


if __name__ == "__main__":
    try:
        main()
    except OOMError as e:
        print("OOM:", e)
        sys.exit(2)
    except Exception as e:
        print("FAILED:", type(e).__name__, e)
        sys.exit(1)
