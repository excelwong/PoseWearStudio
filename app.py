# -*- coding: utf-8 -*-
"""衣姿工坊 PoseWear Studio —— 人物换装 + 姿态参考生成桌面应用。

运行：C:\\AI\\ComfyUI-aki-v3\\python\\python.exe app.py
依赖：本机 ComfyUI 服务 (127.0.0.1:8188)、PyQt6、Pillow、requests
"""
import os
import shutil
import sys
import traceback
from datetime import datetime

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import (QColor, QDesktopServices, QFont, QFontDatabase, QIcon,
                          QPainter, QPen, QPixmap)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from config import (CFG, UNET_MODELS, CLIP_MODELS, VAE_MODELS,  # noqa: E402
                    UNET_DEFAULTS)
from catalog import Catalog                              # noqa: E402
from resolution import RATIOS, TIERS, describe            # noqa: E402
from workflow import (make_prompt, make_negative, ref_tags,  # noqa: E402
                      validate_prompt, apply_keep_background, scene_tail,
                      keep_bg_tail, pose_reference_line, UPPER_BODY_SYSTEM,
                      SCENE_TAIL_KEEP_BG)
from thumbs import ThumbCache, ThumbWorker               # noqa: E402
from generator import GenerateWorker                     # noqa: E402
from comfy_client import ComfyClient                     # noqa: E402

ACCENT = "#2563eb"

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI','Microsoft YaHei','Noto Sans SC','DengXian','Segoe UI',sans-serif; font-size:10pt; color:#1f2937; }
QMainWindow { background:#f4f6f9; }
QGroupBox { background:#ffffff; border:1px solid #e3e8ef; border-radius:10px;
            margin-top:12px; padding:14px 12px 10px 12px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#334155; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background:#ffffff; border:1px solid #d8dee8; border-radius:6px; padding:5px 8px; }
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus { border-color:#2563eb; }
QPushButton { background:#ffffff; border:1px solid #d8dee8; border-radius:6px;
              padding:6px 12px; color:#334155; }
QPushButton:hover { border-color:#93b4fb; background:#f2f6ff; }
QPushButton:disabled { color:#9aa4b2; background:#f1f3f6; }
QPushButton#primary { background:#2563eb; color:#ffffff; border:1px solid #2563eb;
                      font-size:12pt; font-weight:600; padding:11px 16px; }
QPushButton#primary:hover { background:#1d4ed8; }
QPushButton#primary:disabled { background:#9db4e8; border-color:#9db4e8; }
QPushButton#ratio { padding:2px 4px; font-size:9pt; }
QPushButton#ratio:checked { background:#2563eb; color:#ffffff; border-color:#2563eb; font-weight:600; }
QGroupBox#ratioBox { padding:9px 8px 8px 8px; }
QPushButton#keep { color:#2563eb; border-color:#bfcdec; }
QPushButton#keep:checked { background:#2563eb; color:#ffffff; border-color:#2563eb; font-weight:600; }
QListWidget { background:#ffffff; border:1px solid #e3e8ef; border-radius:8px; padding:6px; }
QListWidget::item { border-radius:6px; padding:3px; }
QListWidget::item:selected { background:#dbe7ff; color:#1e3a8a; }
QTabWidget::pane { border:1px solid #e3e8ef; border-radius:8px; background:#ffffff; }
QTabBar::tab { padding:9px 18px; background:#eef1f6; border:1px solid #e3e8ef;
               border-bottom:none; color:#64748b; }
QTabBar::tab:selected { background:#ffffff; color:#2563eb; font-weight:600; }
QProgressBar { border:1px solid #e3e8ef; border-radius:6px; background:#ffffff; height:16px; text-align:center; }
QProgressBar::chunk { background:#2563eb; border-radius:5px; }
QLabel#hint { color:#7b8798; font-size:9pt; }
QLabel#title { font-size:16pt; font-weight:700; color:#0f172a; }
QLabel#sub { font-size:9pt; color:#7b8798; }
"""


def placeholder_pixmap(w=150, h=196):
    pm = QPixmap(w, h)
    pm.fill(QColor("#eceff4"))
    p = QPainter(pm)
    p.setPen(QPen(QColor("#cbd3df"), 1))
    p.drawRect(0, 0, w - 1, h - 1)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "加载中…")
    p.end()
    return pm


class PhotoDrop(QLabel):
    """人物照片拖放 / 预览区。"""
    fileChanged = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(360)
        self.setObjectName("photodrop")
        self.path = None
        self._pix = None
        self._reset()

    def _reset(self):
        self.setStyleSheet("#photodrop{border:2px dashed #b9c6da;border-radius:12px;"
                           "background:#fbfcfe;color:#8492a6;}")
        self.setText("把人物正面照片拖到这里\n或点击选择图片")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_photo(self, path):
        if not path or not os.path.isfile(path):
            return
        pm = QPixmap(path)
        if pm.isNull():
            QMessageBox.warning(self, "提示", "无法读取该图片，请使用 PNG / JPG / WEBP。")
            return
        self.path = path
        self._pix = pm
        self.setStyleSheet("#photodrop{border:1px solid #d8dee8;border-radius:12px;background:#ffffff;}")
        self._draw()

    def _draw(self):
        if self._pix:
            scaled = self._pix.scaled(self.size() - QSize(24, 24),
                                      Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(scaled)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._draw()

    def mousePressEvent(self, e):
        self.pick()

    def pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择人物正面照片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.set_photo(path)
            self.fileChanged.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.set_photo(path)
                self.fileChanged.emit(path)


class Browser(QWidget):
    """素材缩略图浏览器基类（分页 + 本地缩略图缓存 + 后台加载）。"""
    selectionChanged = pyqtSignal(object)

    def __init__(self, cache, page_size=60, keep_text="保持原样",
                 keep_hint="保持原样"):
        super().__init__()
        self.cache = cache
        self.page_size = page_size
        self.all_items = []
        self.page = 0
        self.selected = None
        self.by_path = {}
        self.worker = None
        self.keep_hint = keep_hint
        # 「全裸」按钮只有服装页会创建；基类先占位，姿态页点「保持原姿势」
        # 时才不会因访问不存在的 self.nude_btn 抛 AttributeError（进而被 PyQt abort）。
        self.nude_btn = None

        self.filter_bar = QHBoxLayout()
        self.filter_bar.setContentsMargins(0, 0, 0, 0)
        self.keep_btn = QPushButton(keep_text)
        self.keep_btn.setObjectName("keep")
        self.keep_btn.setCheckable(True)
        self.keep_btn.setToolTip("勾选后不提供该类参考图，保留人物照片中的原样")
        self.keep_btn.clicked.connect(self._keep_original)
        self.filter_bar.addWidget(self.keep_btn)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(150, 196))
        self.list.setGridSize(QSize(172, 238))
        self.list.setSpacing(6)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setWrapping(True)
        self.list.itemClicked.connect(self._on_click)

        bottom = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.next_btn = QPushButton("下一页")
        self.page_label = QLabel("0 / 0")
        self.page_label.setObjectName("hint")
        self.info = QLabel("未选择")
        self.info.setObjectName("hint")
        self.info.setWordWrap(True)
        self.prev_btn.clicked.connect(lambda: self.goto(self.page - 1))
        self.next_btn.clicked.connect(lambda: self.goto(self.page + 1))
        bottom.addWidget(self.prev_btn)
        bottom.addWidget(self.next_btn)
        bottom.addWidget(self.page_label)
        bottom.addStretch(1)
        bottom.addWidget(self.info, 3)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(self.filter_bar)
        lay.addWidget(self.list, 1)
        lay.addLayout(bottom)

    def _filters(self):
        raise NotImplementedError

    def query(self):
        raise NotImplementedError

    def label(self, obj):
        raise NotImplementedError

    def describe(self, obj):
        raise NotImplementedError

    def _stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
        self.worker = None

    def refresh(self):
        self.all_items = self.query()
        self.page = 0
        self.render()

    def goto(self, page):
        total = max(1, (len(self.all_items) + self.page_size - 1) // self.page_size)
        page = max(0, min(page, total - 1))
        if page != self.page:
            self.page = page
            self.render()

    def render(self):
        self._stop_worker()
        self.list.clear()
        self.by_path = {}
        total = max(1, (len(self.all_items) + self.page_size - 1) // self.page_size)
        self.page = min(self.page, total - 1)
        subset = self.all_items[self.page * self.page_size:(self.page + 1) * self.page_size]
        blank = QIcon(placeholder_pixmap())
        for obj in subset:
            item = QListWidgetItem(blank, self.label(obj))
            item.setData(Qt.ItemDataRole.UserRole, obj)
            item.setToolTip(self.describe(obj))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.list.addItem(item)
            self.by_path[obj.path] = item
        self.page_label.setText(f"第 {self.page+1}/{total} 页 · 共 {len(self.all_items)} 项")
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled(self.page < total - 1)
        if not self.all_items:
            self.info.setText("没有匹配的素材")

        self.worker = ThumbWorker([o.path for o in subset], self.cache)
        self.worker.loaded.connect(self._on_thumb)
        self.worker.start()

    def _on_thumb(self, src, thumb_path):
        item = self.by_path.get(src)
        if item is not None:
            item.setIcon(QIcon(thumb_path))

    def _on_click(self, item):
        obj = item.data(Qt.ItemDataRole.UserRole)
        self.selected = obj
        self.keep_btn.setChecked(False)
        if hasattr(self, "nude_btn") and self.nude_btn is not None:
            self.nude_btn.setChecked(False)
        self.info.setText(self.describe(obj))
        self.selectionChanged.emit(obj)

    def _keep_original(self, checked):
        """勾选 = 不提供该类参考图，保留人物照片中的原样。"""
        self.keep_btn.setChecked(checked)
        nude_btn = getattr(self, "nude_btn", None)
        if checked and nude_btn is not None:
            nude_btn.setChecked(False)
        self.selected = None
        self.list.clearSelection()
        if checked:
            self.info.setText(self.keep_hint)
        else:
            self.info.setText("未选择：请点选素材，或勾选「%s」" % self.keep_btn.text())
        self.selectionChanged.emit(None)

    def _toggle_nude(self, checked):
        self.nude_btn.setChecked(checked)
        if checked:
            self.keep_btn.setChecked(False)
            self.selected = None
            self.list.clearSelection()
            self.info.setText("已设为全裸（无服装，附加 completed_nude,slimthick body type with large prominent chest,with a slim waist and a full bust,huge_breasts,large_breasts,small_nipples,sparse_pubic_hair）")
        else:
            self.info.setText("未选择：请点选素材，或勾选「%s」" % self.keep_btn.text())
        self.selectionChanged.emit(None)

    def close(self):
        self._stop_worker()


class CostumeBrowser(Browser):
    def __init__(self, catalog, cache, page_size):
        self.catalog = catalog
        super().__init__(cache, page_size,
                         keep_text="不换装 · 保持原服装",
                         keep_hint="已设为保持原照片中的服装（只改变姿势）")
        self.nude_btn = QPushButton("全裸 · 无服装")
        self.nude_btn.setObjectName("keep")
        self.nude_btn.setCheckable(True)
        self.nude_btn.setToolTip("勾选后生成全裸人像（附加 completed_nude,slimthick body type with large prominent chest,with a slim waist and a full bust,huge_breasts,large_breasts,small_nipples,sparse_pubic_hair）")
        self.nude_btn.clicked.connect(self._toggle_nude)
        self.filter_bar.addWidget(self.nude_btn)
        self.cat = QComboBox()
        self.cat.addItem("全部分类")
        self.cat.addItems(catalog.costume_cats())
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索编号或服装关键词，如 dress / SUM-0001")
        self.cat.currentIndexChanged.connect(lambda _: self.refresh())
        self.search.textChanged.connect(lambda _: self.refresh())
        self.filter_bar.addWidget(QLabel("分类"))
        self.filter_bar.addWidget(self.cat, 1)
        self.filter_bar.addWidget(self.search, 2)
        self.refresh()

    def query(self):
        return self.catalog.filter_costumes(self.cat.currentText(), self.search.text())

    def label(self, obj):
        return f"{obj.id}\n{obj.category}"

    def describe(self, obj):
        return f"{obj.id} · {obj.category} · {obj.keywords}"


class PoseBrowser(Browser):
    """姿态库浏览器：系列变化时额外发信号，让提示词立即换成半身构图句。"""
    systemChanged = pyqtSignal(str)

    def __init__(self, catalog, cache, page_size):
        self.catalog = catalog
        super().__init__(cache, page_size,
                         keep_text="不换姿势 · 保持原姿势",
                         keep_hint="已设为保持原照片中的姿势（只更换服装）")
        self.sys = QComboBox()
        self.sys.addItem("全部系列")
        self.sys.addItems(sorted({p.system for p in catalog.poses}))
        self.cat = QComboBox()
        self.angle = QComboBox()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索姿态名 / 编号，如 站姿 / P015")
        self.sys.currentIndexChanged.connect(self._on_sys)
        self.cat.currentIndexChanged.connect(lambda _: self.refresh())
        self.angle.currentIndexChanged.connect(lambda _: self.refresh())
        self.search.textChanged.connect(lambda _: self.refresh())
        self.filter_bar.addWidget(QLabel("系列"))
        self.filter_bar.addWidget(self.sys, 1)
        self.filter_bar.addWidget(QLabel("分类"))
        self.filter_bar.addWidget(self.cat, 1)
        self.filter_bar.addWidget(self.angle, 1)
        self.filter_bar.addWidget(self.search, 2)
        self._on_sys()

    def _on_sys(self, *_):
        s = self.sys.currentText()
        cur = self.cat.currentText()
        self.cat.blockSignals(True)
        self.cat.clear()
        self.cat.addItem("全部分类")
        self.cat.addItems(self.catalog.pose_cats(s))
        if cur in [self.cat.itemText(i) for i in range(self.cat.count())]:
            self.cat.setCurrentText(cur)
        self.cat.blockSignals(False)
        if self.angle.count() == 0:
            self.angle.addItem("全部角度")
            self.angle.addItems(self.catalog.pose_angles())
        self.refresh()
        self.systemChanged.emit(self.sys.currentText())

    def query(self):
        return self.catalog.filter_poses(self.sys.currentText(), self.cat.currentText(),
                                         self.angle.currentText(), self.search.text())

    def label(self, obj):
        return f"{obj.pose_no} · {obj.name}\n{obj.angle}"

    def describe(self, obj):
        return f"{obj.pose_no} · {obj.name} · {obj.angle} · {obj.system} / {obj.category}"


class StatusWorker(QThread):
    result = pyqtSignal(bool, str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            s = ComfyClient(self.url).status()
            dev = s.get("devices", [{}])[0]
            free = dev.get("vram_free", 0) / 1024 ** 3
            self.result.emit(True, "ComfyUI 已连接 · %.1f GB 显存可用" % free)
        except Exception as e:
            self.result.emit(False, "ComfyUI 未连接 (%s)" % type(e).__name__)


class ImageDialog(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成结果 · " + os.path.basename(path))
        pm = QPixmap(path)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(pm.width() + 40, screen.width() - 100),
                    min(pm.height() + 60, screen.height() - 100))
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(pm.scaled(self.size() - QSize(30, 30),
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
        lay = QVBoxLayout(self)
        lay.addWidget(label)


class MainWindow(QMainWindow):
    def __init__(self, cfg, catalog):
        super().__init__()
        self.cfg = cfg
        self.catalog = catalog
        self.cache = ThumbCache(cfg["cache_dir"])
        self.ratio = "2:3"
        self.megapixels = float(cfg["megapixels"])
        self.costume = None
        self.pose = None
        self.gen_worker = None
        self.last_result = None
        self.ratio_buttons = {}
        self.keep_bg_cb = None       # 在 _build_ui() 中创建；构造期信号触发时安全

        self.setWindowTitle("衣姿工坊 · PoseWear Studio")
        self.resize(1500, 950)
        self.setMinimumHeight(860)
        self._build_ui()
        self._check_status()
        self._update_prompt()

    # ---------------- UI ----------------
    def _build_ui(self):
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 8)
        titles = QVBoxLayout()
        t = QLabel("衣姿工坊  PoseWear Studio")
        t.setObjectName("title")
        s = QLabel("人物照片 + 服装参考 + 姿态参考  →  指定画幅的高清写实人像（本机 ComfyUI / Qwen-Image 2.1）")
        s.setObjectName("sub")
        titles.addWidget(t)
        titles.addWidget(s)
        src = QLabel("素材库：项目内 服装库 / 姿态库  ·  已加载 {} 件服装 / {} 张姿态".format(
            len(self.catalog.costumes), len(self.catalog.poses)))
        src.setObjectName("hint")
        titles.addWidget(src)
        hl.addLayout(titles)
        hl.addStretch(1)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color:#f59e0b;font-size:15pt;")
        self.status_text = QLabel("检测中…")
        self.status_text.setObjectName("hint")
        btn_refresh = QPushButton("重新检测")
        btn_refresh.clicked.connect(self._check_status)
        btn_comfy = QPushButton("打开 ComfyUI")
        btn_comfy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.cfg["comfy_url"])))
        hl.addWidget(self.status_dot)
        hl.addWidget(self.status_text)
        hl.addWidget(btn_refresh)
        hl.addWidget(btn_comfy)

        # ---------- 左侧：三步输入 ----------
        tabs = QTabWidget()
        self.photo = PhotoDrop()
        ptab = QWidget()
        pl = QVBoxLayout(ptab)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.addWidget(self.photo, 1)
        prow = QHBoxLayout()
        pick = QPushButton("选择照片…")
        pick.clicked.connect(self.photo.pick)
        self.person_label = QLabel("未选择照片")
        self.person_label.setObjectName("hint")
        prow.addWidget(pick)
        prow.addWidget(self.person_label, 1)
        pl.addLayout(prow)
        notice = QLabel("仅支持本人或已获授权的成年人肖像，请勿上传未成年人照片。")
        notice.setObjectName("hint")
        notice.setStyleSheet("color:#b45309;")
        pl.addWidget(notice)
        tabs.addTab(ptab, "① 人物照片")

        self.costume_browser = CostumeBrowser(self.catalog, self.cache, self.cfg["page_size"])
        self.costume_browser.selectionChanged.connect(self._on_costume)
        tabs.addTab(self.costume_browser, "② 选择服装")

        self.pose_browser = PoseBrowser(self.catalog, self.cache, self.cfg["page_size"])
        self.pose_browser.selectionChanged.connect(self._on_pose)
        self.pose_browser.systemChanged.connect(self._on_pose_system)
        tabs.addTab(self.pose_browser, "③ 选择姿态")

        # ---------- 三个 tab 之后：始终可见的附加选项 ----------
        bg_bar = QWidget()
        bg_bar.setObjectName("bgbar")
        bg_bar.setStyleSheet(
            "QWidget#bgbar { background:#ffffff; border:1px solid #e3e8ef;"
            " border-radius:10px; }")
        bgl = QVBoxLayout(bg_bar)
        bgl.setContentsMargins(14, 9, 14, 9)
        bgl.setSpacing(3)
        self.keep_bg_cb = QCheckBox("保持原图背景")
        self.keep_bg_cb.setObjectName("keepbg")
        self.keep_bg_cb.setStyleSheet(
            "QCheckBox#keepbg { font-size:10pt; font-weight:600; color:#1e293b; }")
        self.keep_bg_cb.setToolTip(
            "勾选后，提示词中的默认构图/光线/背景整句会替换为：%s；"
            "「上半身单人」系列会保留半身构图约束。" % SCENE_TAIL_KEEP_BG)
        self.keep_bg_cb.toggled.connect(self._on_keep_bg)
        bgl.addWidget(self.keep_bg_cb)
        self.bg_hint = QLabel()
        self.bg_hint.setObjectName("hint")
        self.bg_hint.setWordWrap(True)
        self.bg_hint.setTextFormat(Qt.TextFormat.PlainText)   # 正常显示 <image1>
        bgl.addWidget(self.bg_hint)
        self._update_bg_hint()

        left_col = QWidget()
        lcl = QVBoxLayout(left_col)
        lcl.setContentsMargins(0, 0, 0, 8)
        lcl.setSpacing(8)
        lcl.addWidget(tabs, 1)
        lcl.addWidget(bg_bar)

        # ---------- 右侧：常用 / 高级两个 tab，控件在下方统一组装 ----------
        # ---------- 输出画幅比例：9 个按钮竖向一列，备注只显示分辨率 ----------
        g_ratio = QGroupBox("输出画幅比例")
        g_ratio.setObjectName("ratioBox")
        gl = QVBoxLayout(g_ratio)
        gl.setContentsMargins(4, 4, 4, 4)
        gl.setSpacing(3)
        for key in RATIOS:
            b = QPushButton(key)
            b.setObjectName("ratio")
            b.setCheckable(True)
            b.setChecked(key == self.ratio)
            b.setFixedHeight(22)
            b.clicked.connect(lambda _, k=key: self._set_ratio(k))
            gl.addWidget(b)
            self.ratio_buttons[key] = b
        self.res_label = QLabel()
        self.res_label.setObjectName("hint")
        self.res_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl.addWidget(self.res_label)
        gl.addStretch(1)
        g_ratio.setMaximumWidth(214)
        g_ratio.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        g_size = QGroupBox("生成分辨率")
        sl = QVBoxLayout(g_size)
        hl2 = QHBoxLayout()
        hl2.addWidget(QLabel("像素档位"))
        self.tier = QComboBox()
        self.tier.addItems(list(TIERS.keys()))
        default_tier = next((k for k, v in TIERS.items()
                             if abs(v - self.megapixels) < 1e-6), list(TIERS.keys())[0])
        self.tier.setCurrentText(default_tier)
        self.tier.currentTextChanged.connect(self._set_tier)
        hl2.addWidget(self.tier, 1)
        sl.addLayout(hl2)
        self.tier_tip = QLabel()
        self.tier_tip.setObjectName("hint")
        self.tier_tip.setWordWrap(True)
        sl.addWidget(self.tier_tip)
        self._update_tier_tip()

        g_param = QGroupBox("生成参数")
        pl2 = QGridLayout(g_param)
        self.steps = QSpinBox()
        self.steps.setRange(8, 60)
        self.steps.setValue(int(self.cfg["steps"]))
        self.cfgv = QDoubleSpinBox()
        self.cfgv.setRange(0.5, 8.0)
        self.cfgv.setSingleStep(0.1)
        self.cfgv.setValue(float(self.cfg["cfg"]))
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(0)
        self.refres = QSpinBox()
        self.refres.setRange(0, 4096)
        self.refres.setSingleStep(32)
        self.refres.setValue(int(self.cfg["ref_resolution"]))
        pl2.addWidget(QLabel("步数"), 0, 0); pl2.addWidget(self.steps, 0, 1)
        pl2.addWidget(QLabel("CFG"), 0, 2); pl2.addWidget(self.cfgv, 0, 3)
        pl2.addWidget(QLabel("种子(0=随机)"), 1, 0); pl2.addWidget(self.seed, 1, 1)
        pl2.addWidget(QLabel("参考图边长"), 1, 2); pl2.addWidget(self.refres, 1, 3)
        for _w in (self.steps, self.cfgv, self.seed, self.refres):
            _w.setMinimumWidth(88)

        # ---------- 模型选择：基模 / Text Encoder / VAE ----------
        def _mk_combo(items, current):
            combo = QComboBox()
            for label, value in items:
                combo.addItem(label, value)
            # config.json 里若填了清单之外的名字，也作为额外项保留，不丢用户配置
            if current and combo.findData(current) < 0:
                combo.addItem(str(current), str(current))
            if current:
                i = combo.findData(current)
                if i >= 0:
                    combo.setCurrentIndex(i)
            combo.setMinimumContentsLength(36)
            return combo

        self.unet_combo = _mk_combo(UNET_MODELS, self.cfg["unet"])
        self.clip_combo = _mk_combo(CLIP_MODELS, self.cfg["clip"])
        self.vae_combo = _mk_combo(VAE_MODELS, self.cfg["vae"])
        self.unet_combo.setToolTip("扩散模型，位于 ComfyUI 的 models/diffusion_models/")
        self.clip_combo.setToolTip("文本编码器，位于 models/text_encoders/qwen_image_2.1/")
        self.vae_combo.setToolTip("Qwen-Image 2.1 只能用这个 VAE（唯一可选项）")

        row = 2
        for label, combo in (("基模", self.unet_combo),
                             ("Text Encoder", self.clip_combo),
                             ("VAE", self.vae_combo)):
            pl2.addWidget(QLabel(label), row, 0)
            pl2.addWidget(combo, row, 1, 1, 3)
            row += 1

        # 启动即按当前基模套用推荐组合；connect 放在后面，避免初始化误触发
        self._apply_unet_default(self.unet_combo.currentData())
        self.unet_combo.currentIndexChanged.connect(
            lambda _i: self._apply_unet_default(self.unet_combo.currentData()))

        g_prompt = QGroupBox("提示词（可按需要修改）")
        vl = QVBoxLayout(g_prompt)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("hint")
        self.mode_label.setWordWrap(True)
        vl.addWidget(self.mode_label)
        self.prompt_edit = QPlainTextEdit()
        # 原高度 180px；现在按最终字体行高再额外给出 2 行的可见空间，
        # 并常显垂直滚动条，提示词更长时直接滚动查看，控件高度不再变动。
        self.prompt_edit.ensurePolished()
        line_h = max(1, self.prompt_edit.fontMetrics().lineSpacing())
        self.prompt_edit.setFixedHeight(180 + 2 * line_h)
        self.prompt_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        vl.addWidget(self.prompt_edit)

        self.gen_btn = QPushButton("开始生成")
        self.gen_btn.setObjectName("primary")
        self.gen_btn.clicked.connect(self._generate)
        self.stop_btn = QPushButton("中断当前任务")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._cancel)
        hbtn = QHBoxLayout()
        hbtn.addWidget(self.gen_btn, 3)
        hbtn.addWidget(self.stop_btn, 1)
        # hbtn / progress / stage 放到右侧栏固定底栏（见下方 footer），不随内容滚动

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.stage = QLabel("就绪")
        self.stage.setObjectName("hint")

        g_out = QGroupBox("生成结果")
        ol = QVBoxLayout(g_out)
        self.preview = QLabel("尚未生成")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(160)
        self.preview.setStyleSheet("background:#f8fafc;border:1px solid #e3e8ef;border-radius:8px;color:#94a3b8;")
        self.preview.mousePressEvent = self._show_big
        ol.addWidget(self.preview, 1)
        self.result_info = QLabel("")
        self.result_info.setObjectName("hint")
        self.result_info.setWordWrap(True)
        ol.addWidget(self.result_info)
        # 「打开输出目录」「另存为」改放左列比例组下方，
        # 结果区只保留预览图与信息，最大化图片展示空间。

        # 左列（比例列表 + 结果操作按钮）。注意：变量名不能叫 left_col / lcl，
        # 这两个名字在 _build_ui 开头已用于左侧素材库栏，覆盖会令原栏失去引用被回收。
        ratio_col = QWidget()
        ratio_col.setMaximumWidth(214)
        ratio_col.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        ratio_lay = QVBoxLayout(ratio_col)
        ratio_lay.setContentsMargins(0, 0, 0, 0)
        ratio_lay.setSpacing(8)
        ratio_lay.addWidget(g_ratio)
        bdir = QPushButton("打开输出目录")
        bdir.clicked.connect(lambda: os.startfile(self.cfg["output_dir"]))
        bsave = QPushButton("另存为…")
        bsave.clicked.connect(self._save_as)
        ratio_lay.addWidget(bdir)
        ratio_lay.addWidget(bsave)
        ratio_lay.addStretch(1)

        self.right_tabs = QTabWidget()
        main_tab = QWidget()
        ml = QVBoxLayout(main_tab)
        ml.setContentsMargins(10, 10, 14, 10)
        ml.setSpacing(10)
        ml.addWidget(g_prompt)                  # 提示词固定在最上方
        below = QHBoxLayout()
        below.setSpacing(10)
        below.addWidget(ratio_col)              # 左：比例列表 + 结果操作按钮
        below.addWidget(g_out, 1)               # 右：生成结果（仅预览 + 信息）
        ml.addLayout(below, 1)                  # 下方左右布局占满剩余高度
        self.right_tabs.addTab(main_tab, "生成")

        adv_tab = QWidget()
        al = QVBoxLayout(adv_tab)
        al.setContentsMargins(10, 10, 14, 10)
        al.setSpacing(10)
        adv_tip = QLabel("以下参数不常调整，修改后在下一次生成时读取。")
        adv_tip.setObjectName("hint")
        adv_tip.setWordWrap(True)
        al.addWidget(adv_tip)
        al.addWidget(g_size)
        al.addWidget(g_param)
        al.addStretch(1)
        self.right_tabs.addTab(adv_tab, "分辨率与参数")
        self.right_tabs.setMinimumWidth(470)

        # 固定底栏：任何窗口高度下「开始生成」都可见，不必滚动去找
        footer = QWidget()
        # 必须用带 ID 的限定选择器；裸 background 声明会级联到子按钮，覆盖主按钮配色
        footer.setObjectName("footer")
        footer.setStyleSheet("QWidget#footer { background:#f4f6f9; }")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(10, 8, 14, 10)
        fl.setSpacing(6)
        fl.addLayout(hbtn)
        fl.addWidget(self.progress)
        fl.addWidget(self.stage)
        right_col = QWidget()
        rcl = QVBoxLayout(right_col)
        rcl.setContentsMargins(0, 0, 0, 0)
        rcl.setSpacing(0)
        rcl.addWidget(self.right_tabs, 1)
        rcl.addWidget(footer)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left_col)
        split.addWidget(right_col)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([860, 560])

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(header)
        cl.addWidget(split, 1)
        self.setCentralWidget(central)
        self._update_res_label()

    # ---------------- 交互 ----------------
    def _apply_unet_default(self, unet_value):
        """套用推荐组合：text encoder + 默认步数 + 生成分辨率档位。

        启动时与每次切换基模时各调用一次；用户之后手工改的 encoder / 步数 /
        分辨率档位不会被覆盖，直到下次切换基模。
        清单之外的自定义基模不联动，保留 config.json 里的原始值。
        """
        preset = UNET_DEFAULTS.get(unet_value)
        if not preset:
            return
        clip_label, steps, tier_label = preset
        i = self.clip_combo.findText(clip_label)
        if i >= 0:
            self.clip_combo.setCurrentIndex(i)
        self.steps.setValue(steps)
        # setCurrentText 触发 currentTextChanged → _set_tier()，同步刷新
        # self.megapixels、档位说明与「输出画幅比例」下方的分辨率备注。
        # 档位名必须在 TIERS 里，否则 _set_tier 的 TIERS[text] 会 KeyError。
        if tier_label in TIERS and self.tier.currentText() != tier_label:
            self.tier.setCurrentText(tier_label)

    def _set_ratio(self, key):
        self.ratio = key
        for k, b in self.ratio_buttons.items():
            b.setChecked(k == key)
        self._update_res_label()

    def _set_tier(self, text):
        self.megapixels = TIERS[text]
        self._update_tier_tip()
        self._update_res_label()

    def _update_tier_tip(self):
        max_mp = max(TIERS.values())
        if self.megapixels >= max_mp - 1e-6:
            note = "本机实测最大直出分辨率（4K，约 3 分钟/张）"
        else:
            note = "较快出图档；本机实测上限 {:.1f} MP（4K）".format(max_mp)
        self.tier_tip.setText(
            f"当前 {self.megapixels:.1f} MP：{note}；显存不足时自动降档重试。"
            "尺寸严格符合比例且为 32 的倍数。")

    def _update_res_label(self):
        # 备注只显示最终分辨率，形如 1024:1536；不再显示比例键、px 与 MP
        w, h, _ = describe(self.ratio, self.megapixels)
        self.res_label.setText(f"{w}:{h}")

    def _on_costume(self, obj):
        self.costume = obj
        self._update_prompt()

    def _on_pose(self, obj):
        self.pose = obj
        self._update_prompt()

    def _keep_bg(self):
        return bool(self.keep_bg_cb is not None and self.keep_bg_cb.isChecked())

    def _upper_body(self):
        """姿态来自「上半身单人」系列时改用半身构图句（与安卓版一致）。

        优先看实际选中的姿态参考图；没有姿态参考图时看姿态页当前筛选的系列；
        明确「不换姿势」或「全裸」时不按系列推断，保持原来的全身构图句。
        """
        if self.pose is not None:
            return self.pose.system == UPPER_BODY_SYSTEM
        browser = getattr(self, "pose_browser", None)
        if browser is None:
            return False
        nude_btn = getattr(getattr(self, "costume_browser", None), "nude_btn", None)
        if browser.keep_btn.isChecked() or (nude_btn is not None and nude_btn.isChecked()):
            return False
        return browser.sys.currentText() == UPPER_BODY_SYSTEM

    def _on_pose_system(self, _system):
        self._update_bg_hint()
        self._update_prompt()

    def _on_keep_bg(self, _checked):
        self._update_bg_hint()
        self._update_prompt()

    def _update_bg_hint(self):
        if self._keep_bg():
            self.bg_hint.setText(
                "已启用：提示词末尾改为「%s」" % keep_bg_tail(self._upper_body()))
        else:
            tail = "半身构图" if self._upper_body() else "全身构图"
            self.bg_hint.setText(
                "未勾选：提示词末尾使用默认的构图、光线与简洁背景描述（%s）。" % tail)

    def _set_mode(self, text):
        if self._keep_bg():
            text += " · 保持原图背景"
        if self._upper_body():
            text += " · 半身构图"
        self.mode_label.setText(text)

    def _set_prompt_text(self, text):
        # 对自动生成的所有提示词（含全裸模式）统一替换，保证单一来源
        if self._keep_bg():
            text = apply_keep_background(text, self._upper_body())
        self.prompt_edit.setPlainText(text)

    def _update_prompt(self):
        has_c, has_p = bool(self.costume), bool(self.pose)
        self.nude = self.costume_browser.nude_btn.isChecked()
        upper = self._upper_body()
        if self.nude:
            label = ("全裸 + 换姿势（2 张参考图）" if has_p
                     else "全裸 · 保持原姿势（1 张参考图）")
            self._set_mode("当前模式：" + label)
            self._set_prompt_text(self._nude_prompt(upper))
            return
        if not has_c and not has_p:
            self._set_mode(
                "当前模式：未选择 —— 服装和姿态至少要选一项（或勾选全裸）")
            lines = [
                "# 请先在「② 选择服装」或「③ 选择姿态」中至少选择一项（也可两项都选）。",
                "# 只选服装：保持原姿势、只换装；只选姿态：保持原服装、只换姿势。",
                "# 两项都选：同时换装与换姿势。选择后本提示词会自动生成，也可自行修改。",
                "# 在服装页勾选「全裸 · 无服装」可生成全裸人像（可搭配姿态参考）。",
                "# 勾选左下角「保持原图背景」后，构图/背景描述改为：保持<image1> 的背景、光线不变。",
                "# 姿态选「上半身单人」系列时，构图句自动改为半身取景，不要求腿部入画。",
            ]
            self._set_prompt_text(chr(10).join(lines))
            return
        if has_c and has_p:
            label = "换装 + 换姿势（3 张参考图）"
        elif has_c:
            label = "保持原姿势，只换装（2 张参考图）"
        else:
            label = "保持原服装，只换姿势（2 张参考图）"
        self._set_mode("当前模式：" + label)
        tags = ref_tags(has_c, has_p)
        self._set_prompt_text(make_prompt(
            tags,
            costume_keywords=self.costume.keywords if self.costume else "",
            pose_name=self.pose.name if self.pose else "",
            pose_angle=self.pose.angle if self.pose else "",
            pose_description=self.pose.description if self.pose else "",
            upper_body=upper))

    def _nude_prompt(self, upper_body=False):
        has_p = bool(self.pose)
        if has_p:
            tags = ref_tags(False, True)
            # 姿态参考句与 make_prompt 共用同一函数：统一前缀 + CSV「姿态描述_中文」
            prompt = (
                "以 <image1> 中的女性为主角，严格保持她的面部特征、五官、发型发色、肤色与体型不变。\n"
                "让她完全脱光所有衣物，呈现全裸状态。\n"
                + pose_reference_line(tags["pose"], self.pose.description,
                                      self.pose.name, self.pose.angle) + "\n"
                + scene_tail(upper_body) + "\n"
                + "completed_nude,slimthick body type with large prominent chest,with a slim waist and a full bust,huge_breasts,large_breasts,small_nipples,sparse_pubic_hair"
            )
        else:
            prompt = (
                "以 <image1> 中的女性为主角，严格保持她的面部特征、五官、发型发色、肤色与体型不变。\n"
                "让她完全脱光所有衣物，呈现全裸状态。\n"
                "保持她原本的身体姿势不变。\n"
                + scene_tail(upper_body) + "\n"
                + "completed_nude,slimthick body type with large prominent chest,with a slim waist and a full bust,huge_breasts,large_breasts,small_nipples,sparse_pubic_hair"
            )
        return prompt

    def _check_status(self):
        self.status_dot.setStyleSheet("color:#f59e0b;font-size:15pt;")
        self.status_text.setText("检测中…")
        self._status_worker = StatusWorker(self.cfg["comfy_url"])
        self._status_worker.result.connect(self._on_status)
        self._status_worker.start()

    def _on_status(self, ok, msg):
        self.status_dot.setStyleSheet("color:%s;font-size:15pt;" % ("#16a34a" if ok else "#dc2626"))
        self.status_text.setText(msg)

    def _generate(self):
        if not self.photo.path:
            QMessageBox.information(self, "还差一步", "请先在「① 人物照片」中选择一张正面照片。")
            return
        self.nude = self.costume_browser.nude_btn.isChecked()
        if not self.costume and not self.pose and not self.nude:
            QMessageBox.information(self, "还差一步", chr(10).join([
                "服装和姿态至少要选择一项：", "",
                "· 只选服装 → 保持原姿势，只换装",
                "· 只选姿态 → 保持原服装，只换姿势",
                "· 两项都选 → 同时换装与换姿势",
                "· 勾选「全裸 · 无服装」 → 生成全裸人像（建议搭配姿态参考）"]))
            return
        if self.gen_worker and self.gen_worker.isRunning():
            return
        has_c, has_p = bool(self.costume), bool(self.pose)
        if self.nude:
            text = self.prompt_edit.toPlainText().strip()
            if not has_p:
                n_images = 1
            else:
                tags = ref_tags(False, True)
                n_images = 2
            err = validate_prompt(text, n_images)
            if err:
                QMessageBox.warning(self, "提示词需要更新", err)
                return
            negative = make_negative(ref_tags(False, True)) if has_p else "多个人物，多余肢体，畸形的手指，面部变形，身份不一致，服装，衣物，内衣"
        else:
            tags = ref_tags(has_c, has_p)
            text = self.prompt_edit.toPlainText().strip()
            n_images = 1 + int(has_c) + int(has_p)
            err = validate_prompt(text, n_images)
            if err:
                QMessageBox.warning(self, "提示词需要更新", err)
                return
            negative = make_negative(tags)
        job = {
            "person": self.photo.path,
            "costume": self.costume.path if has_c else None,
            "pose": self.pose.path if has_p else None,
            "nude": self.nude,
            "ratio": self.ratio,
            "megapixels": self.megapixels,
            "prompt": text,
            "negative": negative,
            "seed": self.seed.value(),
            "steps": self.steps.value(),
            "cfg": self.cfgv.value(),
            "ref_resolution": self.refres.value(),
            # 模型三件套由「生成参数」下拉决定，覆盖 config.py 的默认值
            "unet": self.unet_combo.currentData(),
            "clip": self.clip_combo.currentData(),
            "vae": self.vae_combo.currentData(),
        }
        self.gen_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.stage.setText("准备中…")
        self.gen_worker = GenerateWorker(self.cfg, job)
        self.gen_worker.stage.connect(self.stage.setText)
        self.gen_worker.tick.connect(self.stage.setText)
        self.gen_worker.done.connect(self._on_done)
        self.gen_worker.failed.connect(self._on_failed)
        self.gen_worker.start()

    def _cancel(self):
        if self.gen_worker and self.gen_worker.isRunning():
            self.gen_worker.cancel()
            self.stage.setText("正在中断…")

    def _finish_ui(self):
        self.gen_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)

    def _on_done(self, path, info):
        self._finish_ui()
        self.last_result = path
        pm = QPixmap(path)
        if not pm.isNull():
            self.preview.setPixmap(pm.scaled(self.preview.size() - QSize(16, 16),
                                             Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        down = f" · 自动降档 {info['downgraded']} 次" if info["downgraded"] else ""
        self.result_info.setText(
            f"{info['width']}×{info['height']} · {info['megapixels']:.2f} MP · "
            f"{info['ratio']} · 用时 {info['seconds']:.0f} 秒{down}\n{path}")
        self.stage.setText("完成：" + os.path.basename(path))

    def _on_failed(self, msg):
        self._finish_ui()
        self.stage.setText("生成失败")
        QMessageBox.critical(self, "生成失败", msg[:1600])

    def _show_big(self, _e):
        if self.last_result and os.path.isfile(self.last_result):
            ImageDialog(self.last_result, self).exec()

    def _save_as(self):
        if not self.last_result or not os.path.isfile(self.last_result):
            QMessageBox.information(self, "提示", "还没有生成结果。")
            return
        dst, _ = QFileDialog.getSaveFileName(self, "另存为", os.path.basename(self.last_result),
                                             "PNG 图片 (*.png)")
        if dst:
            shutil.copy2(self.last_result, dst)
            self.stage.setText("已另存为 " + dst)

    def closeEvent(self, e):
        self.costume_browser.close()
        self.pose_browser.close()
        if self.gen_worker and self.gen_worker.isRunning():
            self.gen_worker.cancel()
            self.gen_worker.wait(2500)
        e.accept()


_error_dialog_pending = False


def _install_excepthook():
    """PyQt6 中槽函数/事件处理器里未捕获的 Python 异常默认会 abort 整个进程，
    用户看到的就是「异常退出」。这里改成写日志 + 弹窗提示，程序继续运行。"""
    global _error_dialog_pending

    def show(msg, log):
        global _error_dialog_pending
        _error_dialog_pending = False
        try:
            QMessageBox.warning(None, "操作未完成（程序仍在运行）",
                                msg + "\n\n详细信息已写入：\n" + log)
        except Exception:      # 退出过程中弹窗失败也不要引发二次异常
            pass

    def hook(etype, value, tb):
        global _error_dialog_pending
        if issubclass(etype, KeyboardInterrupt):
            sys.__excepthook__(etype, value, tb)
            return
        text = "".join(traceback.format_exception(etype, value, tb))
        log = os.path.join(CFG.get("cache_dir", BASE), "error.log")
        try:
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n=== %s ===\n%s" % (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
        except Exception:
            log = "（日志写入失败）"
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except Exception:
            pass
        brief = ("%s: %s" % (etype.__name__, value or ""))[:300]
        if not _error_dialog_pending:
            _error_dialog_pending = True
            QTimer.singleShot(0, lambda: show(brief, log))

    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    _install_excepthook()
    app.setStyleSheet(STYLE)
    families = set(QFontDatabase.families())
    family = next((x for x in ("Microsoft YaHei UI", "Microsoft YaHei",
                               "Noto Sans SC", "DengXian") if x in families),
                  "Microsoft YaHei UI")
    app.setFont(QFont(family, 9))
    cfg = CFG
    print("素材库根目录:", cfg["library_root"], flush=True)
    catalog = Catalog(cfg["library_root"], cfg["costume_categories"],
                      cfg["pose_systems"], cfg["pose_categories_excluded"])
    print("素材加载:", len(catalog.costumes), "件服装 /",
          len(catalog.poses), "张姿态", flush=True)
    if catalog.errors:
        print("素材库警告:", catalog.errors, flush=True)
        QMessageBox.warning(None, "素材库加载提示", (chr(10) * 2).join(catalog.errors))
    win = MainWindow(cfg, catalog)
    # 启动即最大化；用户点「还原」后回到构造里 resize(1500, 950) 的尺寸。
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
