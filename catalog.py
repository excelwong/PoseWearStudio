# -*- coding: utf-8 -*-
"""读取项目目录下的「服装库」/「姿态库」，构建可检索的素材目录。

root 由 config.py 解析为绝对路径；CSV 中的「原图」列只存文件名，
完整路径按 root/服装库/分类/文件名 与 root/姿态库/系统/分类/文件名 拼接，
因此素材库随项目整体搬迁后无需改动任何数据。

姿态条目额外携带 CSV 的「姿态描述_中文」/「姿态描述_英文」两列：
Qwen-Image 2.1 用中文列、MiniMax-H3-Image 用英文列（H3 需要详细英文整图描述）。
同一姿态的不同角度各行描述不同，必须按当前选中的那条记录取。
"""
import csv
import os
from dataclasses import dataclass


def _is_all(value):
    """界面上的「全部」「全部分类」「全部系列」「全部角度」都表示不过滤。"""
    return not value or str(value).startswith("全部")


@dataclass
class Costume:
    id: str
    category: str
    keywords: str
    path: str


@dataclass
class Pose:
    id: str
    system: str
    category: str
    pose_no: str
    name: str
    angle: str
    prompt: str
    path: str
    # _metadata.csv 的「姿态描述_中文」；旧素材库缺列时为空串，提示词会降级
    description: str = ""
    # _metadata.csv 的「姿态描述_英文」；H3 引擎的提示词直接使用该列
    description_en: str = ""


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class Catalog:
    def __init__(self, root, costume_categories=None, pose_systems=None,
                 pose_categories_excluded=None):
        self.root = os.path.abspath(root)
        self.costume_dir = os.path.join(self.root, "服装库")
        self.pose_dir = os.path.join(self.root, "姿态库")
        self.costume_categories = list(costume_categories or [])
        self.pose_systems = list(pose_systems or [])
        self.pose_excluded = set(pose_categories_excluded or [])
        self.costumes = []
        self.poses = []
        self.errors = []
        self.missing_files = 0
        self.pose_desc_missing = 0
        self.pose_desc_en_missing = 0
        self._load()

    def _check_dir(self, path, label):
        """目录缺失时给出可直接照做的提示，避免界面只是空列表。"""
        if not os.path.isdir(path):
            self.errors.append(
                "找不到{}：{}\n请把素材库放在 config.json 的 library_root "
                "所指目录下（当前：{}）".format(label, path, self.root))
            return False
        return True

    def _load(self):
        cpath = os.path.join(self.costume_dir, "_metadata.csv")
        if self._check_dir(self.costume_dir, "服装库"):
            if os.path.isfile(cpath):
                for row in _read_csv(cpath):
                    cat = row.get("分类", "").strip()
                    if self.costume_categories and cat not in self.costume_categories:
                        continue
                    fn = row.get("原图", "").strip()
                    path = os.path.join(self.costume_dir, cat, fn)
                    if not os.path.isfile(path):
                        self.missing_files += 1
                        continue
                    self.costumes.append(Costume(
                        row.get("id", "").strip(), cat,
                        row.get("关键词(提示词)", "").strip(), path))
            else:
                self.errors.append("缺少服装库 _metadata.csv: " + cpath)

        ppath = os.path.join(self.pose_dir, "_metadata.csv")
        if self._check_dir(self.pose_dir, "姿态库"):
            if os.path.isfile(ppath):
                for row in _read_csv(ppath):
                    system = row.get("系统", "").strip()
                    cat = row.get("分类", "").strip()
                    if self.pose_systems and system not in self.pose_systems:
                        continue
                    if cat in self.pose_excluded:
                        continue
                    fn = row.get("原图", "").strip()
                    path = os.path.join(self.pose_dir, system, cat, fn)
                    if not os.path.isfile(path):
                        self.missing_files += 1
                        continue
                    desc = (row.get("姿态描述_中文") or "").strip()
                    if not desc:
                        self.pose_desc_missing += 1
                    desc_en = (row.get("姿态描述_英文") or "").strip()
                    if not desc_en:
                        self.pose_desc_en_missing += 1
                    self.poses.append(Pose(
                        row.get("id", "").strip(), system, cat,
                        row.get("姿态编号", "").strip(),
                        row.get("姿态名", "").strip(),
                        row.get("角度", "").strip(),
                        row.get("提示词", "").strip(), path, desc, desc_en))
            else:
                self.errors.append("缺少姿态库 _metadata.csv: " + ppath)

        if self.pose_desc_missing:
            self.errors.append(
                "姿态库 _metadata.csv 有 %d 行缺少「姿态描述_中文」列；这些姿态的提示词"
                "将降级为「姿态名 + 角度视角」。请把项目内更新后的 _metadata.csv "
                "同步到素材库目录。" % self.pose_desc_missing)
        if self.pose_desc_en_missing:
            self.errors.append(
                "姿态库 _metadata.csv 有 %d 行缺少「姿态描述_英文」列；H3-Image 的"
                "英文提示词将缺少姿态细节。请把项目内更新后的 _metadata.csv "
                "同步到素材库目录。" % self.pose_desc_en_missing)
        if self.missing_files:
            self.errors.append(
                "有 {} 条素材记录对应的图片文件不存在（可能是复制不完整）".format(
                    self.missing_files))

    def costume_cats(self):
        return sorted({c.category for c in self.costumes})

    def pose_cats(self, system=None):
        return sorted({p.category for p in self.poses
                       if _is_all(system) or p.system == system})

    def pose_angles(self):
        return sorted({p.angle for p in self.poses})

    def filter_costumes(self, category="全部", query=""):
        q = (query or "").strip().lower()
        out = []
        for c in self.costumes:
            if not _is_all(category) and c.category != category:
                continue
            if q and q not in (c.id + " " + c.category + " " + c.keywords).lower():
                continue
            out.append(c)
        return out

    def filter_poses(self, system="全部", category="全部", angle="全部", query=""):
        q = (query or "").strip().lower()
        out = []
        for p in self.poses:
            if not _is_all(system) and p.system != system:
                continue
            if not _is_all(category) and p.category != category:
                continue
            if not _is_all(angle) and p.angle != angle:
                continue
            if q and q not in (p.id + " " + p.name + " " + p.prompt).lower():
                continue
            out.append(p)
        return out
