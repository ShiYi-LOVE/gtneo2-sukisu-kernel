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

# 10) drivers/iio/adc/qcom-spmi-adc5.c: .battemp_for_adc 字段设计符在发布的
#     struct adc_data 中不存在 (闭源头文件未开源), 全文仅此一处引用 —— 删除该行
p = pathlib.Path("drivers/iio/adc/qcom-spmi-adc5.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = "\t.battemp_for_adc = 1,\n"
    if old in t:
        t = t.replace(old, "")
        p.write_text(t)
        patched.append("drivers/iio/adc/qcom-spmi-adc5.c: removed .battemp_for_adc designator (field closed-source)")

# 11) net/oplus_nwpower/oplus_nwpower.c: get_cached_platform_id()/LAGOON 均为闭源
#     API (bitra 回填源中亦无定义)。GT Neo 2 为 kona 平台, platform_id == LAGOON
#     (SM6350) 永不成立 —— 移除该平台检查, 函数行为在本设备上完全不变
p = pathlib.Path("net/oplus_nwpower/oplus_nwpower.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = ("        int platform_id = get_cached_platform_id();\n"
           "        if (platform_id == LAGOON) {\n"
           "                bts_net_clear();\n"
           "        }\n")
    if old in t:
        t = t.replace(old, "")
        p.write_text(t)
        patched.append("net/oplus_nwpower/oplus_nwpower.c: removed closed-source platform check in bts_net_exist")
    elif "get_cached_platform_id" in t:
        # 缩进差异兜底: 用正则移除含两个符号的语句
        t = re.sub(r"\s*int platform_id = get_cached_platform_id\(\);"
                   r"\s*if \(platform_id == LAGOON\) \{\s*bts_net_clear\(\);\s*\}", "", t)
        if "get_cached_platform_id" not in t:
            p.write_text(t)
            patched.append("net/oplus_nwpower/oplus_nwpower.c: platform check removed (regex fallback)")

# 12) drivers/nfc/nq-nci.c: nfcc_hw_check 的 #ifndef OPLUS_BUG_STABILITY 分支
#     (官方出厂定义该宏, 从不编译此分支) 引用了未声明的局部变量 nci_reset_ntf
#     (声明+kzalloc 只存在于 #ifdef 分支) —— 纯源码 bug, 注释掉该 NTF 读取块
#     (该块在任何已知构建里都从未编译过, 移除不影响 NFC 功能)
p = pathlib.Path("drivers/nfc/nq-nci.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = ("\t/* Read Notification of RESET command */\n"
           "\tret = i2c_master_recv(client, nci_reset_ntf, NCI_RESET_NTF_LEN);\n"
           "\tif (ret < 0) {\n"
           "\t\tdev_dbg(&client->dev,\n"
           "\t\t\t\"%s: - Error in getting NFCC HW info\\n\", __func__);\n"
           "\t\tgoto err_nfcc_hw_check;\n"
           "\t}\n")
    if old in t:
        t = t.replace(old, "/* nq-nci: RESET NTF read removed - undeclared nci_reset_ntf in #ifndef OPLUS_BUG_STABILITY branch (never compiled officially) */\n")
        p.write_text(t)
        patched.append("drivers/nfc/nq-nci.c: undeclared nci_reset_ntf read block removed")
    elif "nci_reset_ntf" in t:
        # 兜底: 注释整个含未声明变量的 i2c_master_recv 语句行
        t = re.sub(r"[ \t]*ret = i2c_master_recv\(client, nci_reset_ntf, NCI_RESET_NTF_LEN\);[^\n]*\n",
                   "/* nq-nci: undeclared nci_reset_ntf call removed */\n", t)
        if "nci_reset_ntf" not in t.replace("/* nq-nci: undeclared nci_reset_ntf call removed */", ""):
            p.write_text(t)
            patched.append("drivers/nfc/nq-nci.c: nci_reset_ntf usage removed (regex fallback)")

# 13) drivers/power/reset/msm-poweroff.c: 无守卫引用 PON_RESTART_REASON_NORMAL,
#     但该枚举(及 SILENCE/SAU/RF... 全组)包在 #ifdef OPLUS_BUG_STABILITY 内
#     (include/linux/input/qpnp-power-on.h) —— 官方出厂全局定义该宏。
#     枚举值全部开源, 本文件内 #define 启用完整分支即可; 不做全局定义避免
#     其他文件激活未知闭源代码
p = pathlib.Path("drivers/power/reset/msm-poweroff.c")
if p.exists():
    t = p.read_text(errors="ignore")
    anchor = " */\n\n#include <linux/delay.h>"
    if "OPLUS_BUG_STABILITY" not in t.split("#include")[0] and anchor in t:
        t = t.replace(anchor,
            " */\n\n/* file-local enable: PON_RESTART_REASON_* enums (qpnp-power-on.h)\n"
            "   are guarded by this macro; official builds define it globally */\n"
            "#define OPLUS_BUG_STABILITY\n\n#include <linux/delay.h>", 1)
        p.write_text(t)
        patched.append("drivers/power/reset/msm-poweroff.c: file-local OPLUS_BUG_STABILITY enabled")

# 14) drivers/power/supply/qcom/qpnp-fg-gen4.c: batt-therm probe 块无守卫引用
#     chip->batt_therm_chan, 而该成员声明(287行)与全部其他用法都包在
#     #ifdef OPLUS_FEATURE_CHG_BASIC 内 (宏已因缺失头文件被白名单清理) ——
#     官方源码漏包守卫。给该 probe 块补上与其他用法一致的守卫
p = pathlib.Path("drivers/power/supply/qcom/qpnp-fg-gen4.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = ("\trc = of_property_match_string(fg->dev->of_node, \"io-channel-names\",\n"
           "\t\t\t\t\t\"batt-therm\");\n"
           "\n"
           "\tif (rc >= 0) {\n"
           "\t\tchip->batt_therm_chan = iio_channel_get(fg->dev, \"batt-therm\");\n"
           "\t\t\tif (IS_ERR(chip->batt_therm_chan)) {\n"
           "\t\t\trc = PTR_ERR(chip->batt_therm_chan);\n"
           "\t\t\tif (rc != -EPROBE_DEFER)\n"
           "\t\t\t\tpr_err(\"batt-therm channel unavailable, rc=%d\\n\", rc);\n"
           "\t\t\tchip->batt_therm_chan = NULL;\n"
           "\t\t\treturn rc;\n"
           "\t\t}\n"
           "\t}\n")
    if old in t:
        new = (old[:old.index("\tif (rc >= 0) {")]
               + "#ifdef OPLUS_FEATURE_CHG_BASIC\n"
               + old[old.index("\tif (rc >= 0) {"):]
               + "#endif\n")
        t = t.replace(old, new, 1)
        p.write_text(t)
        patched.append("drivers/power/supply/qcom/qpnp-fg-gen4.c: batt-therm probe block wrapped in OPLUS_FEATURE_CHG_BASIC")
    elif "batt_therm_chan = iio_channel_get" in t:
        # 兜底: 直接禁用引用未声明成员的 iio_channel_get 块
        t = re.sub(r"\tif \(rc >= 0\) \{\s*chip->batt_therm_chan = iio_channel_get.*?\n\t\}\n",
                   "/* fg-gen4: unguarded batt_therm_chan probe block removed */\n", t, count=1, flags=re.S)
        if "batt_therm_chan = iio_channel_get" not in t:
            p.write_text(t)
            patched.append("drivers/power/supply/qcom/qpnp-fg-gen4.c: batt-therm probe block removed (regex fallback)")

# 15) drivers/soc/qcom/subsystem_restart.c: 两处官方依赖闭源 oppo_project.h 的符号
#     a) 313行: 官方把 OPLUS_BUG_STABILITY 守卫注释掉, PREVERSION (闭源枚举) 变成
#        无条件引用 —— 条件恒改 false, 走官方 #else 语义 (restart_level = i, 即
#        stock CAF 行为, 用户版设备永远不满足 PREVERSION)
#     b) 1485行: #ifdef VENDOR_EDIT 的 esoc0 fulldump 块引用 oem_is_fulldump /
#        direct_panic / delay_panic (声明全在 #ifdef OPLUS_BUG_STABILITY 内,
#        本构建不启用) —— 改 #if 0 走 #else 分支 (stock CAF: stay awake + schedule)
p = pathlib.Path("drivers/soc/qcom/subsystem_restart.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old_a = "if(PREVERSION == get_eng_version()){"
    if old_a in t:
        t = t.replace(old_a,
            "if (0) { /* PREVERSION: closed-source eng_version enum; user build -> stock CAF branch */", 1)
        p.write_text(t)
        patched.append("drivers/soc/qcom/subsystem_restart.c: PREVERSION condition neutralized (stock CAF)")
    t = p.read_text(errors="ignore")
    old_b = '\t#ifdef VENDOR_EDIT\n\t\tif (!strcmp(name, "esoc0") && oem_is_fulldump()) {'
    if old_b in t:
        t = t.replace(old_b,
            '#if 0 /* VENDOR_EDIT esoc0 fulldump: oem_is_fulldump/direct_panic/delay_panic closed-source */\n'
            '\t\tif (!strcmp(name, "esoc0") && oem_is_fulldump()) {', 1)
        p.write_text(t)
        patched.append("drivers/soc/qcom/subsystem_restart.c: esoc0 fulldump VENDOR_EDIT block -> #if 0 (stock CAF #else)")

# 16) 全树: soc/oplus/system/oppo_project.h (oppo 拼写) 在开源树中不存在 (include/soc/oplus/system
#     是指向闭源 vendor 的失效符号链接); bitra 回填提供的是 oplus_project.h (oplus 拼写),
#     两者为同一组件, 接口一致 (get_project/is_confidential/get_eng_version 均有实现) —— 统一改名
count = 0
skip_dirs = {".git", "out", "neutron-clang"}
for pat in ("*.c", "*.h"):
    for f in pathlib.Path(".").rglob(pat):
        if any(part in skip_dirs for part in f.parts):
            continue
        try:
            t = f.read_text(errors="ignore")
        except OSError:
            continue
        if "soc/oplus/system/oppo_project.h" in t:
            t = t.replace("soc/oplus/system/oppo_project.h", "soc/oplus/system/oplus_project.h")
            f.write_text(t)
            count += 1
if count:
    patched.append(f"global: renamed oppo_project.h -> oplus_project.h (bitra backfill) in {count} file(s)")

for line in patched:
    print(f"  patched: {line}")
print("file patches done")
