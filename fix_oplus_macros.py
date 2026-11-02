#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动扫描 Oplus 内核树: 找出所有 include 指向不存在文件的代码,
定位其 OPLUS 特性宏守卫, 并从 OplusKernelEnvConfig.mk 的宏白名单中删除。

原理: 闭源 vendor 头文件从未随源码发布, 激活对应 -D 宏只会导致编译失败;
删除白名单宏后, 相关 #ifdef 块整体编译跳过 (社区 bitra 内核同款策略)。
幂等, 可重跑。
"""
import os
import re
import sys

MK = "OplusKernelEnvConfig.mk"
ROOT = "."

def load_whitelist():
    if not os.path.exists(MK):
        return []
    with open(MK, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    macros, in_list = [], False
    for i, ln in enumerate(lines):
        if "ALLOWED_MCROS" in ln and (":=" in ln or "+=" in ln):
            in_list = True
            continue
        if in_list:
            s = ln.strip()
            if s.endswith("\\"):
                tok = s[:-1].strip()
                if tok:
                    macros.append((i, tok))
            else:
                tok = s.strip()
                if tok:
                    macros.append((i, tok))
                in_list = False
    return macros

def scan_missing_includes():
    """返回 {宏名: 缺失头文件路径} (仅统计被 OPLUS 宏守卫的 include)"""
    inc_re = re.compile(r'^\s*#include\s+[<"]([^">]+)[">]')
    guard_re = re.compile(r'^\s*#\s*(ifdef|ifndef)\s+(\w+)|^\s*#\s*if\s+.*defined\s*\(?\s*(\w+)')
    endif_re = re.compile(r'^\s*#\s*endif')
    else_re = re.compile(r'^\s*#\s*else')
    result = {}
    whitelist = {tok for _, tok in load_whitelist()}
    for dirpath, dirnames, filenames in os.walk(ROOT, followlinks=False):
        if ".git" in dirpath or "out/" in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith((".c", ".h")):
                continue
            p = os.path.join(dirpath, fn)
            try:
                lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                continue
            stack = []  # (macro, active) active = True 表示该分支下代码会编译
            for ln in lines:
                g = guard_re.match(ln)
                e = endif_re.match(ln)
                if e:
                    if stack:
                        stack.pop()
                    continue
                if g:
                    name = g.group(2) or g.group(3)
                    neg = g.group(1) == "ifndef"
                    # 只有当外层全部 active 时本层才 active
                    parent_active = all(a for _, a in stack)
                    active = parent_active and ((name in whitelist) != neg)
                    stack.append((name, active))
                    continue
                if else_re.match(ln) and stack:
                    name, _ = stack.pop()
                    parent_active = all(a for _, a in stack)
                    stack.append((name, parent_active and (name in whitelist)))
                    continue
                m = inc_re.match(ln)
                if not m:
                    continue
                if not stack or not all(a for _, a in stack):
                    continue
                inc = m.group(1)
                if not inc.endswith(".h"):
                    continue
                cand = [inc, os.path.join("include", inc)]
                base = os.path.dirname(p)
                if inc.startswith("../"):
                    cand.append(os.path.normpath(os.path.join(base, inc)))
                if not any(os.path.exists(c) for c in cand):
                    for name, active in stack:
                        if active and name.startswith("OPLUS") and name in whitelist:
                            result.setdefault(name, inc)
    return result

def remove_macros(macros):
    if not macros:
        return
    with open(MK, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    removed = 0
    out = []
    for ln in lines:
        s = ln.strip()
        tok = s[:-1].strip() if s.endswith("\\") else s
        if tok in macros and tok.startswith("OPLUS"):
            removed += 1
            continue
        out.append(ln)
    with open(MK, "w", encoding="utf-8") as f:
        f.writelines(out)
    print(f"  removed {removed} macros from whitelist: {sorted(macros)}")

def main():
    bad = scan_missing_includes()
    if not bad:
        print("  no missing-header includes found")
        return
    for macro, inc in sorted(bad.items()):
        print(f"  {macro}: {inc}")
    remove_macros(set(bad))
    # 重扫验证
    still = scan_missing_includes()
    if still:
        print(f"  WARN: still missing after removal: {still}")
        sys.exit(2)
    print("  all missing-header includes resolved via macro removal")

main()
