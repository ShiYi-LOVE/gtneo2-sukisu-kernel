#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""realme 发布源码中「无守卫或宏守卫但依赖闭源符号」的文件级修补。

realme 官方构建环境里这些符号由闭源 vendor 头文件/链接提供, 开源发布后缺失。
处理策略: 还原为 upstream 主线 stock 行为或补齐标准头文件, 不影响功能正确性。
幂等, 逐条容错。
"""
import pathlib
import re

patched = []

# 1) mm/vmscan.c: 官方源码缺少 <linux/proc_fs.h> include (官方由闭源头文件间接引入)
p = pathlib.Path("mm/vmscan.c")
if p.exists():
    t = p.read_text(errors="ignore")
    if "#include <linux/proc_fs.h>" not in t:
        for anchor in ("#include <linux/swap.h>", "#include <linux/mm.h>"):
            if anchor in t:
                t = t.replace(anchor, anchor + "\n#include <linux/proc_fs.h>", 1)
                patched.append("mm/vmscan.c: + #include <linux/proc_fs.h>")
                break
    p.write_text(t)

# 2) kernel/printk/printk.c: VENDOR_EDIT uart-skip 块引用 get_boot_mode /
#    printk_disable_uart / MSM_BOOT_MODE__* —— 发布源码中无定义, 移除整块 (主线 stock 行为)
p = pathlib.Path("kernel/printk/printk.c")
if p.exists():
    t = p.read_text(errors="ignore")
    pat = (r"#ifdef VENDOR_EDIT\n"
           r"\s*if \(\(con->flags & CON_CONSDEV\) &&\n"
           r"\s*\(printk_disable_uart \|\|\n"
           r"\s*get_boot_mode\(\) == MSM_BOOT_MODE__FACTORY \|\|\n"
           r"\s*get_boot_mode\(\) == MSM_BOOT_MODE__RF \|\|\n"
           r"\s*get_boot_mode\(\) == MSM_BOOT_MODE__WLAN\)\)\n"
           r"\s*continue;\n"
           r"#endif /\*VENDOR_EDIT\*/\n")
    new, n = re.subn(pat, "", t)
    if n:
        p.write_text(new)
        patched.append(f"kernel/printk/printk.c: removed {n} vendor uart-skip block(s)")

# 3) mm/vmscan.c: OPLUS_FEATURE_PROCESS_RECLAIM 守卫的 is_reclaim_should_cancel
#    闭源未发布 —— 宏已在白名单中删除, 这里双保险确认调用块条件失效
p = pathlib.Path("mm/vmscan.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = "#if defined(OPLUS_FEATURE_PROCESS_RECLAIM) && defined(CONFIG_PROCESS_RECLAIM_ENHANCE)"
    if old in t:
        t = t.replace(old, "#if 0 /* OPLUS_FEATURE_PROCESS_RECLAIM removed: closed-source impl */")
        p.write_text(t)
        patched.append("mm/vmscan.c: PROCESS_RECLAIM call-site disabled")

for line in patched:
    print(f"  patched: {line}")
print("file patches done")
