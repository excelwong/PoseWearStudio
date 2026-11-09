# -*- coding: utf-8 -*-
"""后台生成线程：上传 → 排队 → 轮询 → 保存。显存不足时自动降档重试。

参考图顺序与 workflow.ref_tags() 严格一致：人物 → 服装（可选）→ 姿态（可选）。
"""
import os
import time
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from comfy_client import ComfyClient, ComfyError, OOMError
from workflow import build
from resolution import calc, tier_steps


class GenerateWorker(QThread):
    stage = pyqtSignal(str)
    tick = pyqtSignal(str)
    done = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(self, cfg, job, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.job = job
        self._cancel = False
        self.client = ComfyClient(cfg["comfy_url"], cfg["request_timeout"])

    def cancel(self):
        self._cancel = True
        try:
            self.client.interrupt()
        except Exception:
            pass

    def _check(self):
        return self._cancel

    def _upload_specs(self):
        """按 <imageN> 顺序返回 [(类别, 本地路径, 上传名), ...]。"""
        tag = self._tag()
        specs = [("person", self.job["person"], "pws_person_%s.png" % tag)]
        if self.job.get("costume"):
            specs.append(("costume", self.job["costume"], "pws_costume_%s.png" % tag))
        if self.job.get("pose"):
            specs.append(("pose", self.job["pose"], "pws_pose_%s.png" % tag))
        return specs

    def run(self):
        job = self.job
        ratio = job["ratio"]
        mp = float(job["megapixels"])
        tiers = tier_steps(mp)
        if not tiers:
            tiers = [mp]

        specs = self._upload_specs()
        # 全裸 + 保持原姿势是合法的 1 张参考图模式（build() 支持 1~3 张）
        if len(specs) < 1:
            self.failed.emit("缺少人物照片，请先在「① 人物照片」中选择图片。")
            return

        uploaded = None
        last_err = None
        mode = " + ".join(k for k, _, _ in specs[1:]) or "仅人物原图"
        self.stage.emit("生成模式：%s（%d 张参考图）" % (mode, len(specs)))

        for idx, tier_mp in enumerate(tiers):
            if self._cancel:
                return
            w, h = calc(ratio, tier_mp)
            if idx > 0:
                self.stage.emit(f"显存不足，自动降至 {w}×{h} 重试（{idx+1}/{len(tiers)}）")
            else:
                self.stage.emit(f"目标 {w}×{h} · {w*h/1e6:.2f} MP")
            try:
                if uploaded is None:
                    self.stage.emit("上传参考图…")
                    uploaded = [self.client.upload(path, name)
                                for _, path, name in specs]
                flow, out_id = build(
                    refs=uploaded,
                    width=w, height=h, prompt=job["prompt"], negative=job.get("negative"),
                    seed=job.get("seed") or None,
                    steps=job["steps"], cfg=job["cfg"],
                    sampler=self.cfg["sampler"], scheduler=self.cfg["scheduler"],
                    unet=self.cfg["unet"], clip=self.cfg["clip"], vae=self.cfg["vae"],
                    clip_type=self.cfg["clip_type"], weight_dtype=self.cfg["weight_dtype"],
                    ref_resolution=job.get("ref_resolution", self.cfg["ref_resolution"]),
                    cache_device=self.cfg["cache_device"], cache_dtype=self.cfg["cache_dtype"],
                    prefix="PoseWearStudio/pw_" + self._tag(),
                )
                self.stage.emit("已提交，正在生成…")
                t0 = time.time()

                def on_tick(elapsed, _q):
                    self.tick.emit("生成中 · 已用时 %d 秒" % int(elapsed))

                pid = self.client.queue(flow)
                entry = self.client.wait(
                    pid, timeout=self.cfg["generation_timeout"],
                    on_tick=on_tick, cancel=self._check)
                imgs = self.client.images(entry, out_id)
                if not imgs:
                    raise ComfyError("ComfyUI 未返回图片")
                data = self.client.fetch(imgs[0])
                name = "pw_%s_%dx%d.png" % (
                    datetime.now().strftime("%Y%m%d_%H%M%S"), w, h)
                path = os.path.join(self.cfg["output_dir"], name)
                with open(path, "wb") as f:
                    f.write(data)
                info = {"width": w, "height": h, "megapixels": w * h / 1e6,
                        "seconds": time.time() - t0, "ratio": ratio,
                        "downgraded": idx, "prompt_id": pid, "mode": mode}
                self.done.emit(path, info)
                return
            except OOMError as e:
                last_err = e
                self.tick.emit("显存不足，尝试降低分辨率…")
                continue
            except ComfyError as e:
                msg = str(e)
                # 部分 OOM 以普通异常形式抛出，同样降档
                if "out of memory" in msg.lower() or "CUDA OOM" in msg:
                    last_err = e
                    self.tick.emit("显存不足，尝试降低分辨率…")
                    continue
                self.failed.emit(msg)
                return
            except Exception as e:
                self.failed.emit("%s: %s" % (type(e).__name__, e))
                return

        self.failed.emit("显存不足，已尝试全部档位仍失败。%s" % (last_err or ""))

    @staticmethod
    def _tag():
        return datetime.now().strftime("%H%M%S") + str(os.getpid())[-3:]
