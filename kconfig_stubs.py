#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Oplus 发布源码缺失 Kconfig/Makefile 占位修复。

realme 官方发布的内核源码不完整:
  - init/Kconfig 引用 kernel/sched_assist/Kconfig、kernel/tuning/Kconfig,
    但发布源码里这些目录是空的;
  - kernel/Makefile 里 obj-y 无条件引用 sched_assist/ 等目录, 缺 Makefile 会导致
    kbuild 下降时报错。
本脚本扫描所有 Kconfig 的 source 引用, 为不存在的目标创建空占位文件;
为 kernel/ 下被 obj-y 引用但缺少 Makefile 的目录创建空 Makefile。
幂等, 逐条容错, 不会中断构建。
"""
import pathlib
import re

KERNEL = pathlib.Path(".")
created = []

# 1) Kconfig source 占位 (仅处理真实相对路径, 跳过含 make 变量的字面量)
for kc in KERNEL.rglob("Kconfig*"):
    if not kc.is_file():
        continue
    try:
        text = kc.read_text(errors="ignore")
    except OSError:
        continue
    for m in re.finditer(r'^\s*source\s+"([^"]+)"', text, re.M):
        src = m.group(1)
        if "$" in src or "/" not in src:
            continue
        target = pathlib.Path(src)
        if target.is_file():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("")
            created.append(str(target))
        except OSError as e:
            print(f"  warn: skip {src}: {e}")

for c in created:
    print(f"  stub: {c}")
if not created:
    print("  no missing Kconfig files")

# 2) kernel/ 下被 obj-y 引用但缺 Makefile 的目录
kmake = pathlib.Path("kernel/Makefile")
if kmake.exists():
    for m in re.finditer(r"^obj-\$\(CONFIG_\w+\)\s*\+=\s*(\S+)/\s*$", kmake.read_text(), re.M):
        d = pathlib.Path("kernel") / m.group(1)
        if d.is_dir() and not (d / "Makefile").exists():
            (d / "Makefile").write_text("")
            print(f"  stub: {d}/Makefile")

print("kconfig stub done")
