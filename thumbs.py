# -*- coding: utf-8 -*-
"""本地缩略图缓存 + 后台生成线程。

素材已随项目放在本地目录，缓存键使用「相对项目根目录的路径」，
因此项目整体搬迁后已有缩略图仍然命中，不必重新生成。
"""
import hashlib
import os

from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal


class ThumbCache:
    def __init__(self, root, size=(170, 220)):
        self.root = os.path.join(root, "thumbs")
        os.makedirs(self.root, exist_ok=True)
        self.size = size
        # root 是 <项目根>/cache，其父目录即项目根目录
        self.base = os.path.dirname(os.path.abspath(root))

    def _target(self, src):
        src = os.path.abspath(src)
        try:
            key = os.path.relpath(src, self.base)
        except ValueError:  # 不同盘符时 relpath 会抛错，退回绝对路径
            key = src
        key = (key.replace(os.sep, "/") + str(self.size)).encode("utf-8", "replace")
        return os.path.join(self.root, hashlib.md5(key).hexdigest() + ".jpg")

    def ensure(self, src):
        """返回缩略图路径；已缓存则直接返回，否则生成。异常时返回 None。"""
        dst = self._target(src)
        if os.path.isfile(dst):
            return dst
        try:
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail(self.size, Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", self.size, (245, 246, 248))
                canvas.paste(im, ((self.size[0] - im.width) // 2,
                                  (self.size[1] - im.height) // 2))
                canvas.save(dst, "JPEG", quality=82, optimize=True)
            return dst
        except Exception:
            return None


class ThumbWorker(QThread):
    """批量生成缩略图。信号只传字符串路径，避免跨线程传递 QPixmap。"""
    loaded = pyqtSignal(str, str)  # 原图路径, 缩略图路径

    def __init__(self, items, cache, parent=None):
        super().__init__(parent)
        self.items = list(items)  # [(原图路径, ...), ...]
        self.cache = cache
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        for src in self.items:
            if self._stop_flag:
                return
            if not src or not os.path.isfile(src):
                continue
            out = self.cache.ensure(src)
            if out and not self._stop_flag:
                self.loaded.emit(src, out)
