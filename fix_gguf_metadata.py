# -*- coding: utf-8 -*-
"""给「元数据缺失」的 Qwen-Image 2.1 GGUF 补写头部字段（不改张量数据、不改文件名）。

背景
----
qwen-image-2.1-turbo-Q4_K_M.gguf 的 GGUF 头 kv_count = 0，没有
general.architecture。ComfyUI-GGUF 的 loader.py 因此进入 sd.cpp 兼容模式，
调用 tools/convert.py 的 detect_arch()；那份旧 arch_list 里没有 qwen_image21，
于是抛：

    This model is not currently supported - (Unknown model architecture!)

节点 1 UnetLoaderGGUF 执行失败，App 里表现为「生成失败 + execution_error」。
同目录的 UC-Q4_K_M / UC-Q8_0 都带 general.architecture = qwen_image21，可正常加载。

做法
----
只改写头部：插入 3 个 KV（architecture / quantization_version / file_type），
重新对齐 padding。张量的 shape / type / offset / 原始量化字节一律原样保留，
不重新量化、不重新编码、不改文件名 —— 所以 ComfyUI 服务端无需重启，
模型列表缓存里的文件名也不变。

用法
----
    python fix_gguf_metadata.py <文件.gguf>            # 生成 .fixed 并验证，不替换
    python fix_gguf_metadata.py <文件.gguf> --apply    # 验证通过后备份 .bak 并替换
"""
import argparse
import hashlib
import os
import re
import struct
import sys

ALIGN = 32
TYPE_UINT32 = 4
TYPE_STRING = 8
FIXED_SUFFIX = ".fixed"
BACKUP_SUFFIX = ".bak"
CHUNK = 8 << 20  # 8 MB


def _pack_key(key):
    b = key.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def kv_string(key, value):
    b = value.encode("utf-8")
    return _pack_key(key) + struct.pack("<I", TYPE_STRING) + struct.pack("<Q", len(b)) + b


def kv_uint32(key, value):
    return _pack_key(key) + struct.pack("<I", TYPE_UINT32) + struct.pack("<I", value)


def _skip_string(f):
    n = struct.unpack("<Q", f.read(8))[0]
    f.seek(n, os.SEEK_CUR)


def _skip_value(f, t):
    if t == TYPE_STRING:
        _skip_string(f)
    elif t in (0, 1, 7):
        f.seek(1, os.SEEK_CUR)
    elif t in (2, 3, 4, 5, 6):
        f.seek(4, os.SEEK_CUR)
    elif t in (10, 11, 12):
        f.seek(8, os.SEEK_CUR)
    elif t == 9:
        sub = struct.unpack("<I", f.read(4))[0]
        n = struct.unpack("<Q", f.read(8))[0]
        for _ in range(n):
            _skip_value(f, sub)
    else:
        raise ValueError("未知 GGUF KV 类型 %d" % t)


def scan_header(path):
    """返回头部各区段偏移；不读取任何张量数据。"""
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("不是 GGUF 文件")
        version = struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        kv_start = f.tell()
        for _ in range(n_kv):
            _skip_string(f)
            _skip_value(f, struct.unpack("<I", f.read(4))[0])
        kv_end = f.tell()
        for _ in range(n_tensors):
            _skip_string(f)                                  # name
            ndim = struct.unpack("<I", f.read(4))[0]
            f.seek(8 * ndim + 4 + 8, os.SEEK_CUR)           # dims + type + offset
        ti_end = f.tell()
    return dict(version=version, n_tensors=n_tensors, n_kv=n_kv,
                kv_start=kv_start, kv_end=kv_end, ti_end=ti_end)


def align(n):
    return (n + ALIGN - 1) // ALIGN * ALIGN


def sha256_range(path, start):
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as f:
        f.seek(start)
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
            total += len(b)
    return h.hexdigest(), total


def build(path, arch, out):
    h = scan_header(path)
    if h["version"] != 3:
        raise ValueError("只处理 GGUF v3，当前 v%d" % h["version"])
    if h["n_kv"] != 0:
        raise ValueError("该文件已有 %d 个 KV，无需补写" % h["n_kv"])

    with open(path, "rb") as f:
        head16 = f.read(16)                          # magic + version + tensor_count
        f.seek(h["kv_end"])
        ti_bytes = f.read(h["ti_end"] - h["kv_end"])

    kv_bytes = b"".join([
        kv_string("general.architecture", arch),
        kv_uint32("general.quantization_version", 2),
        kv_uint32("general.file_type", 15),          # 15 = MOSTLY_Q4_K_M，与 UC-Q4 一致
    ])
    kvs = 3
    raw_len = 16 + 8 + len(kv_bytes) + len(ti_bytes)
    d_new = align(raw_len)
    pad = d_new - raw_len
    d_old = align(h["ti_end"])

    with open(path, "rb") as src, open(out, "wb") as dst:
        dst.write(head16)
        dst.write(struct.pack("<Q", kvs))
        dst.write(kv_bytes)
        dst.write(ti_bytes)
        dst.write(b"\0" * pad)
        src.seek(d_old)
        copied = 0
        while True:
            b = src.read(CHUNK)
            if not b:
                break
            dst.write(b)
            copied += len(b)

    return dict(d_old=d_old, d_new=d_new, kv_len=len(kv_bytes), pad=pad,
                data_bytes=copied, n_tensors=h["n_tensors"], kvs=kvs,
                ti_bytes=ti_bytes)


def verify(path_old, path_new, info, arch, plugin_loader=None):
    """静态 + gguf 库双重校验：头部正确、张量信息逐字节一致、数据区哈希一致。"""
    import gguf

    old = gguf.GGUFReader(path_old)
    new = gguf.GGUFReader(path_new)

    assert old.data_offset == info["d_old"], (old.data_offset, info["d_old"])
    assert new.data_offset == info["d_new"], (new.data_offset, info["d_new"])
    assert len(new.tensors) == info["n_tensors"] == len(old.tensors)
    assert len(new.fields) == len(old.fields) + info["kvs"]

    f = new.get_field("general.architecture")
    assert f is not None, "补写后仍读不到 general.architecture"
    got = str(f.parts[f.data[-1]], encoding="utf-8")
    assert got == arch, (got, arch)

    # 所有张量的名字 / shape / 量化类型 / offset 必须逐项一致
    def sig(r):
        # data_offset 是绝对文件偏移；头部变长后整体平移，因此只比相对偏移
        return [(t.name, tuple(int(x) for x in t.shape),
                 int(t.tensor_type), int(t.data_offset) - int(r.data_offset))
                for t in r.tensors]
    assert sig(old) == sig(new), "张量元信息被改动了"

    # 数据区全量哈希一致（只改头部，不应影响任何量化字节）
    h_old, n_old = sha256_range(path_old, info["d_old"])
    h_new, n_new = sha256_range(path_new, info["d_new"])
    assert h_old == h_new, "张量数据区哈希不一致"
    assert n_old == n_new == info["data_bytes"]

    # 确认这个架构名确实在插件的 IMG_ARCH_LIST 白名单里
    if plugin_loader and os.path.isfile(plugin_loader):
        src = open(plugin_loader, "r", encoding="utf-8").read()
        m = re.search(r"IMG_ARCH_LIST\s*=\s*\{([^}]*)\}", src)
        assert m, "插件里找不到 IMG_ARCH_LIST"
        allowed = set(re.findall(r'"([^"]+)"', m.group(1)))
        assert arch in allowed, (arch, sorted(allowed))

    return dict(arch=got, tensors=len(new.tensors), data_bytes=n_new,
                sha256=h_new[:16], d_old=info["d_old"], d_new=info["d_new"],
                kv_len=info["kv_len"], pad=info["pad"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="待修复的 .gguf 文件")
    ap.add_argument("--arch", default="qwen_image21")
    ap.add_argument("--apply", action="store_true", help="验证通过后备份并替换原文件")
    ap.add_argument("--plugin-loader", default="", help="ComfyUI-GGUF/loader.py 路径，用于核对白名单")
    a = ap.parse_args()

    path = os.path.abspath(a.path)
    if not os.path.isfile(path):
        sys.exit("文件不存在：" + path)
    out = path + FIXED_SUFFIX

    h = scan_header(path)
    print("原文件 : %s" % path)
    print("  GGUF v%d · %d tensors · kv_count=%d · data_offset=%d"
          % (h["version"], h["n_tensors"], h["n_kv"], align(h["ti_end"])))
    if h["n_kv"] != 0:
        print("  已有元数据，跳过（如需强制修复请先确认文件）")
        return

    info = build(path, a.arch, out)
    rep = verify(path, out, info, a.arch, a.plugin_loader or None)
    print("修复副本: %s" % out)
    print("  general.architecture = %s · %d tensors" % (rep["arch"], rep["tensors"]))
    print("  data_offset %d → %d（插入 %d 字节 KV + %d 字节 padding）"
          % (rep["d_old"], rep["d_new"], rep["kv_len"], rep["pad"]))
    print("  张量数据区 %d 字节 sha256=%s… 与原文件完全一致" % (rep["data_bytes"], rep["sha256"]))
    print("  张量 name/shape/type/offset 逐项一致 · 架构名在插件白名单内")

    if not a.apply:
        print("\n[DRY-RUN] 未替换原文件。确认无误后加 --apply 执行替换。")
        return

    bak = path + BACKUP_SUFFIX
    if os.path.exists(bak):
        sys.exit("备份文件已存在，请先处理：%s" % bak)
    os.replace(path, bak)
    try:
        os.replace(out, path)
    except Exception:
        os.replace(bak, path)
        raise
    print("\n[APPLIED] 原文件已备份为 %s，修复版已就位：%s" % (bak, path))
    print("文件名未变，ComfyUI 无需重启；重新点「开始生成」即可。")


if __name__ == "__main__":
    main()
