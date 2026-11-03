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

# 4) fs/proc/meminfo.c: 无条件 include <linux/healthinfo/ion.h> (官方守卫被注释掉),
#    healthinfo 实现整体闭源未发布 —— 注释掉该 include, ION 统计行随
#    OPLUS_FEATURE_HEALTHINFO 宏删除一并编译跳过 (还原主线 stock /proc/meminfo)
for meminfo in ("fs/proc/meminfo.c",):
    p = pathlib.Path(meminfo)
    if p.exists():
        t = p.read_text(errors="ignore")
        inc = "#include <linux/healthinfo/ion.h>"
        if inc in t:
            t = t.replace(inc, "/* healthinfo ion.h include removed: closed-source impl */")
            p.write_text(t)
            patched.append(f"{meminfo}: commented out unconditional healthinfo/ion.h include")

# 5) kernel/sched/cputime.c: account_task_time 调用点守卫 OPLUS_FEATURE_TASK_CPUSTATS,
#    其实现 fs/proc/task_cpustats 闭源未发布 (defconfig 中 #ifdef 包 CONFIG 行无效,
#    CONFIG_OPLUS_CTP/SCHED 实际未开启) —— 宏已在白名单删除, 此处兜底禁用守卫
p = pathlib.Path("kernel/sched/cputime.c")
if p.exists():
    t = p.read_text(errors="ignore")
    if "#ifdef OPLUS_FEATURE_TASK_CPUSTATS" in t:
        t = t.replace("#ifdef OPLUS_FEATURE_TASK_CPUSTATS",
                      "#if 0 /* OPLUS_FEATURE_TASK_CPUSTATS removed: closed-source impl */")
        p.write_text(t)
        patched.append("kernel/sched/cputime.c: TASK_CPUSTATS call-sites disabled")

# 6) 全树兜底: 注释掉对已知闭源头文件的无条件 include
#    (healthinfo/*, task_cpustats.h —— 对应实现/头文件均未开源)
DEAD_HEADERS = ("#include <linux/healthinfo/", "#include <linux/task_cpustats.h>")
count = 0
for pat in ("fs/proc/*.c", "kernel/sched/*.c", "mm/*.c"):
    for f in pathlib.Path(".").glob(pat):
        try:
            t = f.read_text(errors="ignore")
        except OSError:
            continue
        orig = t
        for h in DEAD_HEADERS:
            if h in t:
                t = t.replace(h, "/* " + h + " skipped: closed-source */")
        if t != orig:
            f.write_text(t)
            count += 1
if count:
    patched.append(f"global: commented dead-header includes in {count} file(s)")

# 7) kernel/sched/fair.c: 唯一无守卫的 trace_sched_cpu_sel 调用 (fair.c 其余 sched-assist
#    引用全在 OPLUS_FEATURE_SCHED_ASSIST 块内, 宏删除后自动失效)。该 tracepoint 定义于
#    闭源头文件, 删除此调用 —— 仅影响 ftrace 调试输出, 无功能影响
p = pathlib.Path("kernel/sched/fair.c")
if p.exists():
    t = p.read_text(errors="ignore")
    new, n = re.subn(r"[ \t]*trace_sched_cpu_sel\(.*?\);\n", "", t, flags=re.DOTALL)
    if n:
        p.write_text(new)
        patched.append(f"kernel/sched/fair.c: removed {n} unguarded trace_sched_cpu_sel call(s)")

# 8) kernel/exit.c: 官方源码把 OPLUS_BUG_STABILITY 守卫注释掉了, is_critial_process
#    (官方拼写) 调用变成无条件且全树无定义 —— 注释掉该调试块 (仅影响 printk 输出)
p = pathlib.Path("kernel/exit.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = ("//#ifdef OPLUS_BUG_STABILITY\n"
           "    if (is_critial_process(tsk)) {\n"
           "        printk(\"critical svc %d:%s exit with %ld !\\n\", tsk->pid, tsk->comm,code);\n"
           "    }\n"
           "//#endif /*OPLUS_BUG_STABILITY*/\n")
    if "is_critial_process" in t and old in t:
        t = t.replace(old, "/* OPLUS_BUG_STABILITY debug block removed: is_critial_process undefined in released source */\n")
        p.write_text(t)
        patched.append("kernel/exit.c: removed unguarded is_critial_process debug block")
    elif "is_critial_process" in t:
        # 兜底: 文本与预期不完全一致时, 直接禁用含该调用的行块
        t = re.sub(r"//[#\s]*ifdef OPLUS_BUG_STABILITY.*?//[#\s]*endif[^\n]*\n",
                   "/* removed: is_critial_process undefined */\n", t, flags=re.S)
        if "is_critial_process" not in t:
            p.write_text(t)
            patched.append("kernel/exit.c: is_critial_process block removed (fallback)")

# 9) drivers/block/zram/hybridswap/hybridswap_eswap.c: 官方源码 meminfo_show 定义
#    缺返回类型 (GCC implicit-int 仅告警, Clang -Werror 报错) —— 补上 ssize_t
p = pathlib.Path("drivers/block/zram/hybridswap/hybridswap_eswap.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = "static inline meminfo_show(struct hybstatus *stat, char *buf, ssize_t len)"
    if old in t:
        t = t.replace(old, "static inline ssize_t meminfo_show(struct hybstatus *stat, char *buf, ssize_t len)")
        p.write_text(t)
        patched.append("drivers/block/zram/hybridswap/hybridswap_eswap.c: meminfo_show return type fixed (ssize_t)")

for line in patched:
    print(f"  patched: {line}")
print("file patches done")
