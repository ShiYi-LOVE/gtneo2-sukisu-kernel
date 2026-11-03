#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 KSU_SUSFS_* 的 Kconfig 定义注入 fs/Kconfig。

SukiSU-Ultra main 分支的 kernel/Kconfig 不包含任何 KSU_SUSFS_* 条目
(它们原本来自 susfs4ksu 的 10_enable_susfs_for_ksu.patch, 该补丁只适配
tiann KernelSU, 不适用于 SukiSU 的代码结构)。缺失定义时 scripts/config
写入的 CONFIG_KSU_SUSFS 会在 olddefconfig 时被静默丢弃, 导致:
  - fs/susfs.o 永远不会被编译 (obj-$(CONFIG_KSU_SUSFS))
  - susfs.h 全部 #ifdef 空转
即 SusFS 整体失效。本脚本把定义块追加到 fs/Kconfig (始终被 source),
幂等: 已存在 config KSU_SUSFS 时跳过。
"""
import pathlib

BLOCK = '''
menu "KernelSU - SUSFS"
config KSU_SUSFS
\tbool "KernelSU addon - SUSFS"
\tdepends on KSU
\tdefault y
\thelp
\t  Patch and Enable SUSFS to kernel with KernelSU.

config KSU_SUSFS_HAS_MAGIC_MOUNT
\tbool "Say yes if the current KernelSU repo has magic mount implemented"
\tdepends on KSU
\tdefault y

config KSU_SUSFS_SUS_PATH
\tbool "Enable to hide suspicious path"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_SUS_MOUNT
\tbool "Enable to hide suspicious mounts"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
\tbool "Enable to hide KSU's default mounts automatically"
\tdepends on KSU_SUSFS_SUS_MOUNT
\tdefault y

config KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
\tbool "Enable to hide suspicious bind mounts automatically"
\tdepends on KSU_SUSFS_SUS_MOUNT
\tdefault y

config KSU_SUSFS_SUS_KSTAT
\tbool "Enable to spoof suspicious kstat"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_SUS_OVERLAYFS
\tbool "Enable to automatically spoof kstat/kstatfs for overlayed files"
\tdepends on KSU_SUSFS
\tdefault n

config KSU_SUSFS_TRY_UMOUNT
\tbool "Enable to use ksu's ksu_try_umount"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT
\tbool "Enable to add bind mounts to ksu's ksu_try_umount automatically"
\tdepends on KSU_SUSFS_TRY_UMOUNT
\tdefault y

config KSU_SUSFS_SPOOF_UNAME
\tbool "Enable to spoof uname"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_ENABLE_LOG
\tbool "Enable logging susfs log to kernel"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
\tbool "Enable to hide ksu/susfs symbols from /proc/kallsyms"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
\tbool "Enable to spoof /proc/cmdline (non-gki)"
\tdepends on KSU_SUSFS
\tdefault y

config KSU_SUSFS_OPEN_REDIRECT
\tbool "Enable to redirect a path to be opened with another path"
\tdepends on KSU_SUSFS
\tdefault y

endmenu
'''

p = pathlib.Path("fs/Kconfig")
t = p.read_text(encoding="utf-8", errors="ignore")
if "config KSU_SUSFS" in t:
    print("  fs/Kconfig 已包含 KSU_SUSFS 定义, 跳过")
else:
    p.write_text(t.rstrip("\n") + "\n" + BLOCK, encoding="utf-8")
    print("  fs/Kconfig: 已注入 KSU_SUSFS 定义块 (15 项)")

# 自检: 逐项确认 build.sh 使用的 CONFIG 符号都有定义
import re
need = [
    "KSU_SUSFS", "KSU_SUSFS_HAS_MAGIC_MOUNT", "KSU_SUSFS_SUS_PATH",
    "KSU_SUSFS_SUS_MOUNT", "KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT",
    "KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT", "KSU_SUSFS_SUS_KSTAT",
    "KSU_SUSFS_TRY_UMOUNT", "KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT",
    "KSU_SUSFS_SPOOF_UNAME", "KSU_SUSFS_ENABLE_LOG",
    "KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS", "KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG",
    "KSU_SUSFS_OPEN_REDIRECT",
]
t2 = p.read_text(encoding="utf-8", errors="ignore")
defined = set(re.findall(r"^config (\w+)$", t2, re.M))
missing = [n for n in need if n not in defined]
print("  自检:", "全部符号有定义" if not missing else f"缺失 {missing}")
raise SystemExit(1 if missing else 0)
