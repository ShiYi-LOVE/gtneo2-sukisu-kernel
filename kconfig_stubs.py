#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Oplus 发布源码的缺失组件占位修复。

realme 官方发布的内核源码有两个问题:
1. 大量符号链接指向未发布的 vendor/oplus/kernel/* 目录 (如 kernel/sched_assist
   -> ../../../vendor/oplus/kernel/oplus_performance/sched_assist/), clone 后全部失效;
2. 部分 Kconfig 的 source 引用目标文件不存在。

处理策略 (与社区 bitra 内核做法一致 —— 直接禁用这些闭源功能):
  - 目标以 "/" 结尾的失效符号链接 -> 替换为真实空目录 (内含空 Kconfig 与 Makefile);
  - 仍缺失的 Kconfig source 目标 -> 创建空占位文件;
  - kernel/ 下被 obj-* 引用但缺 Makefile 的目录 -> 补空 Makefile。
幂等, 逐条容错。
"""
import os
import pathlib
import re

fixed_links = []

# 1) 失效的目录型符号链接 -> 真实空目录
for dirpath, dirnames, filenames in os.walk(".", followlinks=False):
    for name in list(dirnames) + list(filenames):
        p = pathlib.Path(dirpath) / name
        try:
            if p.is_symlink() and not p.exists():
                target = os.readlink(p)
                if target.endswith("/"):
                    p.unlink()
                    p.mkdir(parents=True, exist_ok=True)
                    (p / "Kconfig").touch()
                    (p / "Makefile").touch()
                    fixed_links.append(f"{p} -> {target}")
        except OSError as e:
            print(f"  warn: {p}: {e}")

for f in fixed_links:
    print(f"  fixed broken symlink: {f}")
if not fixed_links:
    print("  no broken directory symlinks")

# 2) Kconfig source 占位
created = []
for dirpath, dirnames, filenames in os.walk(".", followlinks=False):
    if ".git" in dirpath:
        continue
    for fn in filenames:
        if not fn.startswith("Kconfig"):
            continue
        kc = pathlib.Path(dirpath) / fn
        try:
            text = kc.read_text(errors="ignore")
        except OSError:
            continue
        for m in re.finditer(r'^\s*source\s+"([^"]+)"', text, re.M):
            src = m.group(1)
            if "$" in src or "/" not in src:
                continue
            target = pathlib.Path(src)
            if target.is_file() or target.is_symlink():
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("")
                created.append(str(target))
            except OSError as e:
                print(f"  warn: skip {src}: {e}")

for c in sorted(set(created)):
    print(f"  stub: {c}")
if not created:
    print("  no missing Kconfig files")

# 3) kernel/ 下被 obj-* 引用但缺 Makefile 的目录
kmake = pathlib.Path("kernel/Makefile")
if kmake.exists():
    for m in re.finditer(r"^obj-\$\(CONFIG_\w+\)\s*\+=\s*(\S+)/\s*$", kmake.read_text(), re.M):
        d = pathlib.Path("kernel") / m.group(1)
        if d.is_dir() and not (d / "Makefile").exists():
            (d / "Makefile").write_text("")
            print(f"  stub: {d}/Makefile")

print("kconfig stub done")
