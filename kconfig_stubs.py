#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Oplus 发布源码的缺失组件占位修复。

realme 官方发布的内核源码里, 大量符号链接指向未发布的 vendor/oplus/kernel/*
目录 (如 kernel/sched_assist -> ../../../vendor/oplus/kernel/.../sched_assist/),
clone 后全部失效; 另有部分 Kconfig source 引用的文件不存在。

处理策略 (与社区 bitra 内核做法一致 —— 直接禁用这些闭源功能):
  1. 删除所有失效符号链接;
  2. 若被 Kconfig source "<路径>/Kconfig" 或 kernel/Makefile obj-* 引用,
     重建为真实目录 (内含空 Kconfig + Makefile), 否则重建为空文件;
  3. 仍缺失的 Kconfig source 目标 -> 创建空占位文件。
幂等, 逐条容错, 重建跑两轮以处理嵌套失效链接。
"""
import os
import pathlib
import re

ROOT = pathlib.Path(".")

# 预扫描: 所有 Kconfig source 引用
src_refs = set()
for dirpath, dirnames, filenames in os.walk(".", followlinks=False):
    if ".git" in dirpath:
        continue
    for fn in filenames:
        if not fn.startswith("Kconfig"):
            continue
        try:
            text = (pathlib.Path(dirpath) / fn).read_text(errors="ignore")
        except OSError:
            continue
        # 匹配带引号与不带引号两种 source 写法 (Oplus 源码两种都有)
        for m in re.finditer(r'^\s*source\s+"?([^"\s]+?)"?\s*$', text, re.M):
            s = m.group(1)
            if "$" not in s and "/" in s:
                src_refs.add(s)

dir_kconfig_refs = {s.rsplit("/Kconfig", 1)[0] for s in src_refs if s.endswith("/Kconfig")}

# kernel/Makefile 里 obj-* 引用的子目录 (子目录里通常还要有 Makefile)
obj_dirs = set()
kmake = pathlib.Path("kernel/Makefile")
if kmake.exists():
    for m in re.finditer(r"^obj-\$\(CONFIG_\w+\)\s*\+=\s*(\S+)/?\s*$", kmake.read_text(), re.M):
        obj_dirs.add(m.group(1).rstrip("/"))

# 1) 失效符号链接 -> 删除并按引用方式重建 (跑两轮处理嵌套)
fixed = []
for _round in range(2):
    for dirpath, dirnames, filenames in os.walk(".", followlinks=False):
        for name in list(dirnames) + list(filenames):
            p = pathlib.Path(dirpath) / name
            try:
                if not (p.is_symlink() and not p.exists()):
                    continue
                target = os.readlink(p)
                p.unlink()
                rel = str(p).lstrip("./")
                if target.endswith("/") or rel in dir_kconfig_refs or rel in obj_dirs:
                    p.mkdir(parents=True, exist_ok=True)
                    (p / "Kconfig").touch()
                    (p / "Makefile").touch()
                else:
                    p.write_text("")
                fixed.append(f"{rel} -> {target}")
            except OSError as e:
                print(f"  warn: {p}: {e}")

for f in fixed:
    print(f"  fixed broken symlink: {f}")
if not fixed:
    print("  no broken symlinks")

# 2) 仍缺失的 Kconfig source 占位
created = []
for s in sorted(src_refs):
    target = pathlib.Path(s)
    if target.is_file():
        continue
    try:
        # 路径本身是符号链接 (无论失效或指向缺 Kconfig 的目录) -> 移除后重建
        if target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")
        created.append(s)
    except OSError as e:
        print(f"  warn: skip {s}: {e}")

for c in created:
    print(f"  stub: {c}")
if not created:
    print("  no missing Kconfig files")

# 3) obj-* 引用目录的 Makefile 占位
for d in sorted(obj_dirs):
    dp = pathlib.Path("kernel") / d
    if dp.is_dir() and not (dp / "Makefile").exists():
        (dp / "Makefile").write_text("")
        print(f"  stub: {dp}/Makefile")

print("kconfig stub done")
