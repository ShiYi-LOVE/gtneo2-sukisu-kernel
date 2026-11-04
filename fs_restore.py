#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补回 realme 未随 T 版本源码发布的三个文件系统组件。

问题链条 (r34 定位):
  realme 把 ext4(oplus 定制版)/erofs/exfat 的源码放在 vendor/oplus/kernel_4.19/
  下, 没有随 AndroidT 源码发布。fs/Kconfig 里 source 的是
      "fs/oext4/Kconfig"   "fs/erofs/Kconfig"   "fs/exfat/Kconfig"
  而这三个目录全是指向 vendor/oplus/kernel_4.19/ 的失效符号链接
  -> kconfig_stubs.py 把它们重建成空目录
  -> CONFIG_EXT4_FS / EROFS_FS / EXFAT_FS 三个符号在 Kconfig 里根本不存在
  -> defconfig 里明明写了 =y, olddefconfig 仍然丢弃
  -> 编出来的内核没有 ext4、没有 erofs, 只有 f2fs

后果 (对照原厂 boot.img 内 ramdisk 的 fstab.qcom):
  /metadata   ext4  first_stage_mount   <- Android 第一阶段必须挂载
  /cache /persist /vendor/dsp /my_custom   全部 ext4
  system/system_ext/product/vendor/odm     ext4 或 erofs
  /data       f2fs   (唯一本来就支持的)
  => 第一阶段 init 挂不上 /metadata, 直接卡在开机 logo

修复:
  用同厂商 realmeGT-Neo2_AndroidR-kernel-source 仓库里完整发布的
  fs/oext4 (46 文件) / fs/erofs (23 文件) / fs/exfat (25 文件) 覆盖。
  该仓库同为 4.19 线、同为 OPLUS 定制, Kconfig 符号与原厂 config 一一对应
  (CONFIG_OPLUS_FEATURE_OEXT4 / EROFS_FS_CLUSTER_PAGE_LIMIT / OPLUS_FEATURE_EROFS)。

调用时机: 必须在 kconfig_stubs.py 之后 (否则符号链接重建会覆盖回去)。
"""
import os
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(".")
ZIP = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "fs_vendor.zip")

TARGETS = ("fs/oext4", "fs/erofs", "fs/exfat")

if not ZIP.is_file():
    print("FATAL: 找不到源码包 %s" % ZIP)
    sys.exit(1)

with zipfile.ZipFile(ZIP) as z:
    names = [n for n in z.namelist() if not n.endswith("/")]

print("   源码包 %s: %d 个文件" % (ZIP.name, len(names)))

for t in TARGETS:
    p = ROOT / t
    if p.is_symlink():
        try:
            tgt = os.readlink(p)
        except OSError:
            tgt = "?"
        p.unlink()
        print("   移除失效符号链接: %s -> %s" % (t, tgt))
    elif p.is_dir():
        shutil.rmtree(p)
        print("   清空旧目录: %s" % t)
    elif p.exists():
        p.unlink()

with zipfile.ZipFile(ZIP) as z:
    for n in names:
        dest = ROOT / n
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(n) as fsrc, open(dest, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)

# --- 自检: 只要有一个不成立就直接失败, 避免又打出一个没有 ext4 的内核 ---
checks = {
    "fs/oext4/Kconfig": "config EXT4_FS",
    "fs/oext4/Makefile": "",
    "fs/erofs/Kconfig": "config EROFS_FS",
    "fs/erofs/super.c": "erofs",
    "fs/erofs/Makefile": "erofs-objs",
    "fs/exfat/Kconfig": "config EXFAT_FS",
    "fs/exfat/exfat_core.c": "exfat",
    "fs/ext4/super.c": "ext4",
    "fs/jbd2/journal.c": "",
    "fs/crypto/keyinfo.c": "",
}
bad = []
for f, kw in checks.items():
    p = ROOT / f
    if not p.is_file():
        bad.append("%s 缺失" % f)
        continue
    size = p.stat().st_size
    if size == 0:
        bad.append("%s 是空文件" % f)
        continue
    if kw:
        txt = p.read_text(errors="ignore")
        if kw not in txt:
            bad.append("%s 不含 %r" % (f, kw))
            continue
    print("   OK %-24s %6d 字节" % (f, size))

if bad:
    print("FATAL: 文件系统源码补全失败 -> " + "; ".join(bad))
    sys.exit(1)

print("fs_restore done")
