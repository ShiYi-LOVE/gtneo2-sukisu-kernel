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

# 3) mm/vmscan.c: 调用 is_reclaim_should_cancel() —— 官方树里该符号闭源未发布。
# !! r44 教训: 原实现把 `#if defined(OPLUS_FEATURE_PROCESS_RECLAIM) && defined(CONFIG_PROCESS_RECLAIM_ENHANCE)`
#    整串替换成 `#if 0`。这串条件在 vmscan.c 里出现 3 次(函数签名分支 / .walk 初始化 / 调用点),
#    str.replace 全部命中 -> 函数定义退化成 2 参数, 而 include/linux/rmap.h 里同条件仍是
#    3 参数声明 -> "conflicting types for 'reclaim_pages_from_list'"。
#    改法: 只在符号确实没有定义时才砍掉"调用点"两行, 绝不碰条件表达式本身。
vp = pathlib.Path("mm/vmscan.c")
if vp.exists():
    vt = vp.read_text(errors="ignore")
    if "is_reclaim_should_cancel" in vt:
        defined_elsewhere = False
        for d in ("mm", "include", "kernel", "drivers"):
            if defined_elsewhere or not pathlib.Path(d).exists():
                continue
            for f in pathlib.Path(d).rglob("*.[ch]"):
                if f.as_posix() == "mm/vmscan.c":
                    continue
                try:
                    if "is_reclaim_should_cancel" in f.read_text(errors="ignore"):
                        defined_elsewhere = True
                        break
                except OSError:
                    continue
        if defined_elsewhere:
            patched.append("mm/vmscan.c: is_reclaim_should_cancel 本树已有定义, 保留原调用")
        else:
            nv, n = re.subn(
                r"[ \t]*if \(sc->walk && is_reclaim_should_cancel\(sc->walk\)\)\s*\n\s*break;",
                "/* is_reclaim_should_cancel: closed-source impl, call removed */",
                vt)
            if n:
                vp.write_text(nv)
                patched.append(f"mm/vmscan.c: removed {n} is_reclaim_should_cancel call-site(s) only")

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

# 5) kernel/sched/cputime.c: ctp_send_message / sched_action_trig 来自闭源的
#    fs/proc/task_cpustats (其 include/linux/task_cpustats.h 两套树都没有)。
#    守卫有两种写法, 都要覆盖 (r44 教训: 只处理了 #ifdef 形式, 漏了复合形式,
#    结果 cputime.c:533 的 `#if defined(OPLUS_FEATURE_TASK_CPUSTATS) && defined(CONFIG_OPLUS_SCHED)`
#    仍然成立, 报 use of undeclared identifier 'ctp_send_message')
CPUTIME_GUARDS = (
    ("#ifdef OPLUS_FEATURE_TASK_CPUSTATS",
     "#if 0 /* OPLUS_FEATURE_TASK_CPUSTATS removed: closed-source impl */"),
    ("#if defined(OPLUS_FEATURE_TASK_CPUSTATS) && defined(CONFIG_OPLUS_SCHED)",
     "#if 0 /* TASK_CPUSTATS && OPLUS_SCHED removed: ctp_send_message is closed-source */"),
)
p = pathlib.Path("kernel/sched/cputime.c")
if p.exists():
    t = p.read_text(errors="ignore")
    orig = t
    for old, new in CPUTIME_GUARDS:
        t = t.replace(old, new)
    if t != orig:
        p.write_text(t)
        patched.append("kernel/sched/cputime.c: TASK_CPUSTATS call-sites disabled (both guard forms)")

# 6) 全树兜底: 注释掉对「真的不存在」的闭源头文件的无条件 include
#    (healthinfo/*, task_cpustats.h)
# !! r43 教训: 早期版本按路径前缀盲替, 结果在自带 include/linux/healthinfo/fg.h 的
#    community 树上把 `#include <linux/healthinfo/fg.h>` 替换成
#      /* #include <linux/healthinfo/ skipped: closed-source */fg.h>
#    —— 只切掉了前缀, 剩下的 "fg.h>" 变成裸 token, clang 报 "unknown type name 'fg'",
#    连带 is_fg() 隐式声明 (链接期必炸)。
#    现在改成: 先解析出完整头文件名并确认文件确实不存在, 再整行注释。
DEAD_PREFIXES = ("linux/healthinfo/", "linux/task_cpustats.h")
INC_LINE_RE = re.compile(r'^[ \t]*#include[ \t]+<([^>]+)>[ \t]*$', re.M)


def _header_exists(inc, src_dir):
    cands = [inc,
             "include/" + inc,
             "arch/arm64/include/" + inc,
             "include/uapi/" + inc]
    if inc.startswith(("../", "./")):
        cands.append((pathlib.Path(src_dir) / inc).as_posix())
    return any(pathlib.Path(c).exists() for c in cands)


count = 0
for pat in ("fs/proc/*.c", "kernel/sched/*.c", "mm/*.c"):
    for f in pathlib.Path(".").glob(pat):
        try:
            t = f.read_text(errors="ignore")
        except OSError:
            continue
        orig = t

        def _kill(m):
            inc = m.group(1)
            if not inc.startswith(DEAD_PREFIXES):
                return m.group(0)
            if _header_exists(inc, f.parent):
                # 树里真有这个头 -> 一行都不许动
                return m.group(0)
            return "/* " + m.group(0).strip() + " skipped: header absent in this tree */"

        t = INC_LINE_RE.sub(_kill, t)
        if t != orig:
            f.write_text(t)
            count += 1
if count:
    patched.append(f"global: commented {count} file(s) with genuinely-absent closed-source includes")

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

# 17) drivers/staging/android/ion/ion_system_heap.c: CONFIG_OPLUS_ION_BOOSTPOOL 已禁用
#     (闭源失效符号链接组件), 编译走 #ifndef stock 路径, 但路径内仍有 3 处活跃引用
#     NR_IONCACHE_PAGES —— 该 vmstat 枚举项在 mmzone.h/vmstat.c 由
#     OPLUS_FEATURE_HEALTHINFO 守卫 (宏已因闭源清理)。不能文件级 define (枚举跨
#     编译单元错位会破坏 zone 统计), 3 处均为启动预填/预留优化, 中性化还原 stock 行为:
#     a) shrink 循环的 "预留 200MB" 检查 -> 移除 (stock CAF 无此检查)
#     b) fill_pool_kworkthread 启动预填 while 条件 -> 改为有界 for 循环 (总页数不变)
p = pathlib.Path("drivers/staging/android/ion/ion_system_heap.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old_a = ("#ifndef CONFIG_OPLUS_ION_BOOSTPOOL\n"
             "\t\t/*\n"
             "\t\t * Keep minimum 200 MB in the pool so that camera launch latency would remain\n"
             "\t\t * low under heavy memory pressure also.\n"
             "\t\t */\n"
             "\t\tif (global_zone_page_state(NR_IONCACHE_PAGES) < MIN_ION_POOL_PAGES)\n"
             "\t\t\tbreak;\n"
             "#endif\n")
    if old_a in t:
        t = t.replace(old_a,
            "\t\t/* min-pool reserve check removed: NR_IONCACHE_PAGES is an\n"
            "\t\t * OPLUS_FEATURE_HEALTHINFO vmstat item (closed in released source);\n"
            "\t\t * stock CAF shrink path has no such check */\n", 1)
        p.write_text(t)
        patched.append("drivers/staging/android/ion/ion_system_heap.c: 200MB min-pool reserve check removed")
    t = p.read_text(errors="ignore")
    old_b = ("\tfor (i = 0; i < NUM_ORDERS; i++) {\n"
             "\t\twhile (global_zone_page_state(NR_IONCACHE_PAGES) <\n"
             "\t\t\t\tMIN_ION_POOL_PAGES_BOOTUP) {\n"
             "\t\t\tif (fill_page_pool(sh->heap.priv, sh->cached_pools[i]) < 0)\n"
             "\t\t\t\tbreak;\n"
             "\t\t}\n"
             "\t}")
    new_b = ("\tfor (i = 0; i < NUM_ORDERS; i++) {\n"
             "\t\tint j;\n"
             "\t\tfor (j = 0; j < MIN_ION_POOL_PAGES_BOOTUP / NUM_ORDERS; j++) {\n"
             "\t\t\tif (fill_page_pool(sh->heap.priv, sh->cached_pools[i]) < 0)\n"
             "\t\t\t\tbreak;\n"
             "\t\t}\n"
             "\t}")
    old_c = ("\tfor (i = 0; i < NUM_ORDERS; i++) {\n"
             "\t\twhile (global_zone_page_state(NR_IONCACHE_PAGES) <\n"
             "\t\t\t\t(2 * MIN_ION_POOL_PAGES_BOOTUP)) {\n"
             "\t\t\tif (fill_page_pool(sh->heap.priv, sh->uncached_pools[i]) < 0)\n"
             "\t\t\t\tbreak;\n"
             "\t\t}\n"
             "\t}")
    new_c = ("\tfor (i = 0; i < NUM_ORDERS; i++) {\n"
             "\t\tint j;\n"
             "\t\tfor (j = 0; j < (2 * MIN_ION_POOL_PAGES_BOOTUP) / NUM_ORDERS; j++) {\n"
             "\t\t\tif (fill_page_pool(sh->heap.priv, sh->uncached_pools[i]) < 0)\n"
             "\t\t\t\tbreak;\n"
             "\t\t}\n"
             "\t}")
    n = 0
    if old_b in t:
        t = t.replace(old_b, new_b, 1); n += 1
    if old_c in t:
        t = t.replace(old_c, new_c, 1); n += 1
    if n:
        p.write_text(t)
        patched.append(f"drivers/staging/android/ion/ion_system_heap.c: boot-prefetch while -> bounded for ({n} sites)")
    elif "NR_IONCACHE_PAGES" in t:
        # 兜底: 全局替换仍存活的 NR_IONCACHE_PAGES 条目为安全上界写法
        t = re.sub(r"while \(global_zone_page_state\(NR_IONCACHE_PAGES\) <\s*\(?([\dA-Z_ *]+)\)?\) \{",
                   r"while (fill_count++ < \1 / NUM_ORDERS) {", t)
        p.write_text(t)
        patched.append("drivers/staging/android/ion/ion_system_heap.c: NR_IONCACHE_PAGES uses replaced (regex fallback)")

# 18) drivers/soc/qcom/fsa4480-i2c.c: #include "dsi/dsi_display.h" (techpack/display
#     未开源, 官方源码 techpack 只有 stub) + get_main_display()/dsi_parser_utils 引用。
#     仅用于读取 DT 属性 "oplus,dp-support-customized" 决定 DP 方向寄存器值;
#     GT Neo2 USB-C 无 DP alt-mode, 取 false (走 oplus 非 DP 分支, 与设备一致)
p = pathlib.Path("drivers/soc/qcom/fsa4480-i2c.c")
if p.exists():
    t = p.read_text(errors="ignore")
    inc = '#include "dsi/dsi_display.h"\n'
    if inc in t:
        t = t.replace(inc, "/* dsi_display.h include removed: techpack/display not open-sourced */\n", 1)
        p.write_text(t)
        patched.append("drivers/soc/qcom/fsa4480-i2c.c: closed dsi/dsi_display.h include removed")
    t = p.read_text(errors="ignore")
    old = ('\tstruct dsi_display *display = get_main_display();\n'
           '\tstruct dsi_parser_utils *utils = &display->panel->utils;\n'
           '\tbool oplus_dp_support = utils->read_bool(utils->data, "oplus,dp-support-customized");\n')
    if old in t:
        t = t.replace(old,
            '\t/* dsi_display (techpack/display) not open-sourced; GT Neo2 USB-C has no\n'
            '\t * DP alt-mode -> oplus_dp_support false, matches device DT */\n'
            '\tbool oplus_dp_support = false;\n', 1)
        p.write_text(t)
        patched.append("drivers/soc/qcom/fsa4480-i2c.c: get_main_display block -> oplus_dp_support = false")

# 19) drivers/usb/pd/policy_engine.c: pd_lobal 定义(514行)在 #ifdef OPLUS_FEATURE_CHG_BASIC
#     内 (宏已闭源清理), 其余 4 处使用全在守卫块内 (死代码), 唯独 typec_is_otg_mode()
#     (2091行) 无守卫引用 —— 官方源码漏包守卫。该函数全树零调用方、无 EXPORT_SYMBOL,
#     整体移除零行为影响
p = pathlib.Path("drivers/usb/pd/policy_engine.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = ("bool typec_is_otg_mode(void)\n"
           "{\n"
           "\tif (pd_lobal != NULL)\n"
           "\t\treturn pd_lobal->is_otg_mode;\n"
           "\telse\n"
           "\t\treturn false;\n"
           "}\n")
    if old in t:
        t = t.replace(old,
            "/* typec_is_otg_mode removed: references pd_lobal guarded by OPLUS_FEATURE_CHG_BASIC\n"
            "   (closed in released source); function has no callers and no EXPORT_SYMBOL */\n", 1)
        p.write_text(t)
        patched.append("drivers/usb/pd/policy_engine.c: dead typec_is_otg_mode() removed")
    elif "typec_is_otg_mode" in t:
        # 兜底: 禁用函数体
        t = re.sub(r"bool typec_is_otg_mode\(void\)\s*\{.*?\n\}",
                   "/* typec_is_otg_mode removed (regex fallback) */", t, count=1, flags=re.S)
        p.write_text(t)
        patched.append("drivers/usb/pd/policy_engine.c: typec_is_otg_mode removed (regex fallback)")

# 20) mm/vmscan.c: kswapd_threads (官方定义被注释, 闭源环境提供) -> 用同文件开源的
#     kswapd_threads_current (同一默认值 DEF_KSWAPD_THREADS_PER_NODE)
p = pathlib.Path("mm/vmscan.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = "\tnr_threads = kswapd_threads;\n"
    if old in t:
        t = t.replace(old, "\tnr_threads = kswapd_threads_current;\n", 1)
        p.write_text(t)
        patched.append("mm/vmscan.c: kswapd_threads -> kswapd_threads_current")

# 21) drivers/soc/qcom/oplus_watchdog_util.c: cpu_idle_pc_state (extern 数组, 提供者
#     在闭源 cpuidle 驱动) -> 本地定义全零数组 (永远不视为 PC 空闲, 仅影响
#     watchdog 调试 ping mask 的收缩范围)
# !!! 仅在树里"真的没人提供"这个符号时才补 !!!
# bigshot 的 watchdog_v2.c 里有:
#     #ifndef OPLUS_BUG_STABILITY / static int cpu_idle_pc_state[NR_CPUS];
#     #else                           / int cpu_idle_pc_state[NR_CPUS]; / #endif
# 而 OplusKernelEnvConfig.mk 会 -DOPLUS_BUG_STABILITY, 所以它走 #else 提供了全局定义。
# 这时再在 oplus_watchdog_util.c 里本地定义一次, 链接期就是
#   ld.lld: error: duplicate symbol: cpu_idle_pc_state   (r54 实测)
p = pathlib.Path("drivers/soc/qcom/oplus_watchdog_util.c")
_wd = pathlib.Path("drivers/soc/qcom/watchdog_v2.c")
_provided = False
if _wd.exists():
    for _ln in _wd.read_text(errors="ignore").splitlines():
        # 全局定义形如 "int cpu_idle_pc_state[NR_CPUS];" (顶格, 无 static)
        if _ln.startswith("int cpu_idle_pc_state"):
            _provided = True
            break
if p.exists() and not _provided:
    t = p.read_text(errors="ignore")
    old = "extern int cpu_idle_pc_state[NR_CPUS];"
    if old in t:
        t = t.replace(old,
            "int cpu_idle_pc_state[NR_CPUS]; /* local zeroed: closed-source cpuidle provider */", 1)
        p.write_text(t)
        patched.append("drivers/soc/qcom/oplus_watchdog_util.c: cpu_idle_pc_state defined locally (zeroed)")
elif p.exists() and _provided:
    patched.append("drivers/soc/qcom/oplus_watchdog_util.c: 跳过本地定义 "
                   "(watchdog_v2.c 已提供全局 cpu_idle_pc_state, 再定义会 duplicate symbol)")

# 22) drivers/soc/qcom/subsys-pil-tz.c log_failure_reason: oplus_kevent_fb_str /
#     mdmreason_set (崩溃遥测, 提供者闭源) -> 中性化 (仅影响遥测上报)
p = pathlib.Path("drivers/soc/qcom/subsys-pil-tz.c")
if p.exists():
    t = p.read_text(errors="ignore")
    n = 0
    if "\t\toplus_kevent_fb_str(FB_SENSOR, FB_SENSOR_ID_CRASH, reason);\n" in t:
        t = t.replace("\t\toplus_kevent_fb_str(FB_SENSOR, FB_SENSOR_ID_CRASH, reason);\n",
                      "\t\t/* oplus_kevent_fb_str skipped: closed */\n", 1); n += 1
    if "mdmreason_set(reason);" in t:
        t = t.replace("        mdmreason_set(reason);",
                      "        /* mdmreason_set skipped: closed */", 1); n += 1
    if n:
        p.write_text(t)
        patched.append(f"drivers/soc/qcom/subsys-pil-tz.c: {n} closed telemetry calls neutered")

# 23) drivers/soc/qcom/subsystem_restart.c: op_restart_modem 定义在 OPLUS_BUG_STABILITY
#     守卫内 (未启用), force_rst_write 调用点无守卫 -> 中性化 (调试 sysfs 功能)
p = pathlib.Path("drivers/soc/qcom/subsystem_restart.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = "\t\top_restart_modem(subsys);\n"
    if old in t:
        t = t.replace(old, "\t\t/* op_restart_modem skipped: definition guarded by inactive OPLUS_BUG_STABILITY */\n", 1)
        p.write_text(t)
        patched.append("drivers/soc/qcom/subsystem_restart.c: op_restart_modem call neutered")

# 24) drivers/soc/oplus/sensor/oplus_ssc_interact/oplus_ssc_interact.c (bitra 回填):
#     register/unregister_lcdinfo_notifier 提供者未回填 (bitra 构建走 panel_event 分支,
#     本构建走 #else 分支) -> 中性化 (低亮模式传感器联动降级)
p = pathlib.Path("drivers/soc/oplus/sensor/oplus_ssc_interact/oplus_ssc_interact.c")
if p.exists():
    t = p.read_text(errors="ignore")
    n = 0
    if "\t\t\tregister_lcdinfo_notifier(&ssc_cxt->nb);\n" in t:
        t = t.replace("\t\t\tregister_lcdinfo_notifier(&ssc_cxt->nb);\n",
                      "\t\t\t/* register_lcdinfo_notifier skipped: provider closed */\n", 1); n += 1
    if "\tunregister_lcdinfo_notifier(&ssc_cxt->nb);\n" in t:
        t = t.replace("\tunregister_lcdinfo_notifier(&ssc_cxt->nb);\n",
                      "\t/* unregister_lcdinfo_notifier skipped: provider closed */\n", 1); n += 1
    if n:
        p.write_text(t)
        patched.append(f"drivers/soc/oplus/.../oplus_ssc_interact.c: {n} lcdinfo notifier calls neutered")

# 25) drivers/soc/oplus/sensor/oplus_sensor_feedback/sensor_feedback.c (bitra 回填):
#     CONFIG_DRM_MSM 分支调用 msm_drm_register_client (techpack/display 闭源) ->
#     禁用该分支, 走 #elif CONFIG_FB 的标准 fb_register_client
p = pathlib.Path("drivers/soc/oplus/sensor/oplus_sensor_feedback/sensor_feedback.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = "#if defined(CONFIG_DRM_MSM)\n\tsensor_fb_cxt->fb_notif.notifier_call = sensor_fb_notifier;\n\terr = msm_drm_register_client(&sensor_fb_cxt->fb_notif);"
    if old in t:
        t = t.replace(old,
            "#if 0 /* msm_drm_register_client: techpack/display closed; use FB notifier */ && defined(CONFIG_DRM_MSM)\n\tsensor_fb_cxt->fb_notif.notifier_call = sensor_fb_notifier;\n\terr = msm_drm_register_client(&sensor_fb_cxt->fb_notif);", 1)
        p.write_text(t)
        patched.append("drivers/soc/oplus/.../sensor_feedback.c: DRM_MSM branch disabled, FB notifier used")

# 26) drivers/block/zram/hybridswap/hybridswap_swapd.c: msm_drm_(un)register_client
#     (techpack/display 闭源) -> 中性化全部调用, 保留 goto/label 结构
p = pathlib.Path("drivers/block/zram/hybridswap/hybridswap_swapd.c")
if p.exists():
    t = p.read_text(errors="ignore")
    n = 0
    old = "\tret = msm_drm_register_client(&fb_notif);\n"
    if old in t:
        t = t.replace(old, "\tret = 0; /* msm_drm_register_client removed: techpack/display closed */\n"); n += 1
    old2 = "\tmsm_drm_unregister_client(&fb_notif);\n"
    if old2 in t:
        t = t.replace(old2, "\t/* msm_drm_unregister_client removed: techpack/display closed */\n"); n += 1
    if n:
        p.write_text(t)
        patched.append(f"drivers/block/zram/hybridswap/hybridswap_swapd.c: {n} msm_drm calls neutered")

# 27) drivers/net/wireless/cnss2/main.c: kevent_send_to_user (oplus_kevent 闭源) ->
#     中性化 (仅影响 WLAN 自恢复遥测上报)
p = pathlib.Path("drivers/net/wireless/cnss2/main.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = "\tkevent_send_to_user(cnss_event);\n"
    if old in t:
        t = t.replace(old, "\t/* kevent_send_to_user skipped: oplus_kevent closed */\n", 1)
        p.write_text(t)
        patched.append("drivers/net/wireless/cnss2/main.c: kevent_send_to_user neutered")

# 28) drivers/usb/pd/policy_engine.c: oplus_wpc_set_wrx_en_value (无线充电闭源, GT Neo2
#     无 wpc 硬件) -> 中性化全部调用 (全文件共 4 处: 1 处 (1), 3 处 (0))
p = pathlib.Path("drivers/usb/pd/policy_engine.c")
if p.exists():
    t = p.read_text(errors="ignore")
    new, n = re.subn(r"(\t+)oplus_wpc_set_wrx_en_value\(\d\);",
                     r"\1/* oplus_wpc_set_wrx_en_value skipped: closed, no wpc hw */", t)
    if n:
        p.write_text(new)
        patched.append(f"drivers/usb/pd/policy_engine.c: {n} oplus_wpc_set_wrx_en_value calls neutered")

# 29) drivers/power/supply/qcom/Makefile: OPLUS_FEATURE_CHG_BASIC 分支排除了
#     qpnp-smb5.o smb5-lib.o (被闭源 oplus 充电驱动替代), 但 schgm-flash.o 仍在构建且
#     依赖 smblib_* (定义于 smb5-lib.c, 开源存在) -> 回补两个目标, qcom stock 充电栈
#     恢复链接 (probe 由 DT 决定, 无节点则不运行)
# !!! 只在树里没有 oplus 充电驱动时才补 !!!
# bigshot 带 drivers/power/oplus/v1/charger_ic/oplus_battery_msm8250.c, 它自己又实现了
# 一整套 smblib_read/write/masked_write... , 回补后链接期直接
#   ld.lld: error: duplicate symbol: smblib_read  (smb5-lib.o vs oplus_battery_msm8250.o)
p = pathlib.Path("drivers/power/supply/qcom/Makefile")
_oplus_smb = False
_oplus_dir = pathlib.Path("drivers/power/oplus")
if _oplus_dir.is_dir():
    for _f in _oplus_dir.rglob("*.c"):
        try:
            if "smblib_read" in _f.read_text(errors="ignore"):
                _oplus_smb = True
                break
        except OSError:
            pass
if p.exists() and not _oplus_smb:
    t = p.read_text(errors="ignore")
    old = "obj-$(CONFIG_QPNP_SMB5)\t\t+= step-chg-jeita.o battery.o pmic-voter.o storm-watch.o schgm-flash.o\n"
    if old in t:
        t = t.replace(old,
            "obj-$(CONFIG_QPNP_SMB5)\t\t+= step-chg-jeita.o battery.o pmic-voter.o storm-watch.o schgm-flash.o qpnp-smb5.o smb5-lib.o\n", 1)
        p.write_text(t)
        patched.append("drivers/power/supply/qcom/Makefile: + qpnp-smb5.o smb5-lib.o restored")
elif _oplus_smb:
    patched.append("drivers/power/supply/qcom/Makefile: 跳过回补 "
                   "(OPPO 充电驱动自带 smblib_*, 再补 smb5-lib.o 会 duplicate symbol)")

# 30) drivers/esoc/esoc-mdm-4x.c: mdmreason_set (modem 重启原因记录, 实现闭源;
#     第 2 个调用方, 第 29 轮 subsys-pil-tz.c 已处理第 1 个) -> 中性化,
#     保留 __subsystem_send_uevent (开源, 定义于 subsystem_restart.c)
p = pathlib.Path("drivers/esoc/esoc-mdm-4x.c")
if p.exists():
    t = p.read_text(errors="ignore")
    n = 0
    old_a = '\t\t\t\t\tmdmreason_set("Force modem reset");\n'
    if old_a in t:
        t = t.replace(old_a, '\t\t\t\t\t/* mdmreason_set skipped: closed impl */\n', 1); n += 1
    old_b = '\t\t\t\t\tmdmreason_set(sfr_buf2);\n'
    if old_b in t:
        t = t.replace(old_b, '\t\t\t\t\t/* mdmreason_set skipped: closed impl */\n', 1); n += 1
    if n:
        p.write_text(t)
        patched.append(f"drivers/esoc/esoc-mdm-4x.c: {n} mdmreason_set calls neutered")

# 31) include/linux/vermagic.h: 内核以 CONFIG_MODVERSIONS=n 编译 (绕开 genksyms
#     对 gsi_write_channel_scratch 的 CRC 生成缺陷), 但原厂 vendor 模块的 vermagic
#     带 "modversions" 标志, 字符串必须逐字一致才能加载 -> 硬写入 VERMAGIC_STRING。
#     因 MODVERSIONS=n, 加载时不做 CRC 校验, 只比对 vermagic。
p = pathlib.Path("include/linux/vermagic.h")
if p.exists():
    t = p.read_text(errors="ignore")
    old = ('#ifdef CONFIG_MODVERSIONS\n'
           '#define MODULE_VERMAGIC_MODVERSIONS "modversions "\n'
           '#else\n'
           '#define MODULE_VERMAGIC_MODVERSIONS ""\n'
           '#endif\n')
    new = ('/* 强制与 vendor 模块 vermagic 对齐: 恒带 modversions 标志 */\n'
           '#define MODULE_VERMAGIC_MODVERSIONS "modversions "\n')
    if old in t:
        p.write_text(t.replace(old, new, 1))
        patched.append("include/linux/vermagic.h: modversions flag forced")

# 32) kernel/module.c: module_sig_check() 在模块带签名但无法用本内核密钥链验证时
#     直接返回错误 (MODULE_SIG_FORCE=n 也拦不住), 原厂 vendor 模块用真我私钥签名,
#     我们编不出同密钥 -> 一律放行 (保留 CONFIG_MODULE_SIG=y 只为维持 struct module
#     布局与原厂一致, 布局变化会让模块的 this_module 段错位)。
p = pathlib.Path("kernel/module.c")
if p.exists():
    t = p.read_text(errors="ignore")
    if "OPLUS_ANY_MODULE_SIG_OK" not in t:
        idx = t.find("static int module_sig_check(struct load_info *info, int flags)")
        if idx >= 0:
            anchor = "const void *mod = info->hdr;\n"
            j = t.find(anchor, idx)
            if j >= 0:
                ins = j + len(anchor)
                patch_txt = ("\t/* OPLUS_ANY_MODULE_SIG_OK: 放行厂商签名模块 (无本内核密钥) */\n"
                             "\treturn 0;\n")
                t = t[:ins] + patch_txt + t[ins:]
                p.write_text(t)
                patched.append("kernel/module.c: module_sig_check accepts any signature")

# 33) include/linux/module.h: SukiSU-Ultra main 分支 kernel/core/init.c 末尾无条件写
#     MODULE_IMPORT_NS(VFS_internal_I_am_really_a_filesystem_and_am_NOT_a_driver);
#     该宏是 5.4 才有的"符号命名空间"机制, 4.19 完全没有定义
#     -> 预处理后剩 `MODULE_IMPORT_NS(X);` 裸标识符, clang 报
#        282:1 warning: type specifier missing, defaults to 'int'
#        282:18 error: a parameter list without types is only allowed in a function definition
#     4.19 没有命名空间导出/导入这回事, 直接定义为空宏即可 (语义等价于"不需要导入")。
p = pathlib.Path("include/linux/module.h")
if p.exists():
    t = p.read_text(errors="ignore")
    if "OPLUS_COMPAT_MODULE_IMPORT_NS" not in t:
        block = (
            "/* OPLUS_COMPAT_MODULE_IMPORT_NS: 4.19 无符号命名空间, SukiSU 用到该宏 */\n"
            "#ifndef MODULE_IMPORT_NS\n"
            "#define MODULE_IMPORT_NS(ns)\n"
            "#endif\n"
        )
        guard = "#define _LINUX_MODULE_H\n"
        idx = t.find(guard)
        if idx >= 0:
            ins = idx + len(guard)
            t = t[:ins] + block + t[ins:]
        else:
            t = t + "\n" + block
        p.write_text(t)
        patched.append("include/linux/module.h: MODULE_IMPORT_NS no-op (4.19)")

# 34) include/linux/pgtable.h: SukiSU 的 feature/sucompat.c 无条件
#     #include <linux/pgtable.h>, 该头是 5.x 才从 arch/*/include/asm/pgtable.h
#     拆出来的公共层, 4.19 的 include/linux 下没有这个文件
#     -> fatal error: 'linux/pgtable.h' file not found
#     做法: 建一个转发头, 4.19 的等价内容就在 asm/pgtable.h。
#     已确认同一文件里 #include <linux/static_call.h> 有 >=6.12 守卫, 无需补;
#     <linux/version.h> 由 kbuild 生成, 能正常解析 (core/init.c 已编过)。
pg = pathlib.Path("include/linux/pgtable.h")
if not pg.exists():
    pg.parent.mkdir(parents=True, exist_ok=True)
    pg.write_text(
        "/* OPLUS_COMPAT_LINUX_PGTABLE_H: 4.19 无 include/linux/pgtable.h,\n"
        " * 该头 5.x 才从 asm/pgtable.h 拆出; SukiSU 无条件包含, 这里做转发。 */\n"
        "#ifndef _LINUX_PGTABLE_H\n"
        "#define _LINUX_PGTABLE_H\n"
        "#include <asm/pgtable.h>\n"
        "#endif\n"
    )
    patched.append("include/linux/pgtable.h: shim -> asm/pgtable.h (4.19 无此头)")

# 35) drivers/kernelsu/infra/file_wrapper.c: SukiSU 该文件按 5.x 基线写,
#     用了两个 4.19 的 struct file_operations 里不存在的成员:
#       iopoll            -> 5.1 才有 (4.19 的 fops 无此成员)
#       remap_file_range  -> 5.0 才有, REMAP_FILE_DEDUP 同样 5.0 才有
#     报错: no member named 'iopoll' / 'remap_file_range'; use of undeclared
#           identifier 'REMAP_FILE_DEDUP'
#     做法: 给这四段(两个函数 + 两处赋值)加 >= 5.1 / >= 5.0 守卫; 不赋值时
#     成员保持 0, 语义等价于"内核不支持该操作", 4.19 上本来就该是 0。
fw = pathlib.Path("drivers/kernelsu/infra/file_wrapper.c")
if fw.exists():
    t = fw.read_text(errors="ignore")
    orig_t = t
    if "OPLUS_419_NO_IOPOLL" not in t:
        # (a) iopoll 函数体整体包起来
        old_a = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)\n"
                 "static int ksu_wrapper_iopoll(struct kiocb *kiocb, struct io_comp_batch *icb, unsigned int v)")
        new_a = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 1, 0) /* OPLUS_419_NO_IOPOLL */\n"
                 "#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)\n"
                 "static int ksu_wrapper_iopoll(struct kiocb *kiocb, struct io_comp_batch *icb, unsigned int v)")
        if old_a in t:
            t = t.replace(old_a, new_a, 1)
        old_a2 = ("    return orig->f_op->iopoll(kiocb, spin);\n"
                  "}\n"
                  "#endif\n")
        new_a2 = ("    return orig->f_op->iopoll(kiocb, spin);\n"
                  "}\n"
                  "#endif\n"
                  "#endif /* LINUX_VERSION_CODE < 5.1: 4.19 无 f_op->iopoll */\n")
        if old_a2 in t:
            t = t.replace(old_a2, new_a2, 1)
        # (b) 赋值处守卫
        old_b = "    p->ops.iopoll = fp->f_op->iopoll ? ksu_wrapper_iopoll : NULL;\n"
        new_b = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 1, 0)\n"
                 "    p->ops.iopoll = fp->f_op->iopoll ? ksu_wrapper_iopoll : NULL;\n"
                 "#endif\n")
        if old_b in t:
            t = t.replace(old_b, new_b, 1)
        # (c) remap_file_range 函数体
        old_c = ("static loff_t ksu_wrapper_remap_file_range(struct file *file_in, loff_t pos_in, struct file *file_out, loff_t pos_out,")
        new_c = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 0, 0) /* OPLUS_419_NO_REMAP */\n"
                 "static loff_t ksu_wrapper_remap_file_range(struct file *file_in, loff_t pos_in, struct file *file_out, loff_t pos_out,")
        if old_c in t:
            t = t.replace(old_c, new_c, 1)
        old_c2 = ("        return orig->f_op->remap_file_range(orig, pos_in, file_out, pos_out, len, remap_flags);\n"
                  "    }\n"
                  "}\n")
        new_c2 = ("        return orig->f_op->remap_file_range(orig, pos_in, file_out, pos_out, len, remap_flags);\n"
                  "    }\n"
                  "}\n"
                  "#endif /* LINUX_VERSION_CODE < 5.0: 4.19 无 remap_file_range */\n")
        if old_c2 in t:
            t = t.replace(old_c2, new_c2, 1)
        # (d) 赋值处守卫
        old_d = "    p->ops.remap_file_range = fp->f_op->remap_file_range ? ksu_wrapper_remap_file_range : NULL;\n"
        new_d = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 0, 0)\n"
                 "    p->ops.remap_file_range = fp->f_op->remap_file_range ? ksu_wrapper_remap_file_range : NULL;\n"
                 "#endif\n")
        if old_d in t:
            t = t.replace(old_d, new_d, 1)
    if t != orig_t:
        fw.write_text(t)
        patched.append("drivers/kernelsu/infra/file_wrapper.c: iopoll>=5.1 / remap>=5.0 守卫")

# 36) SukiSU 还有两处 5.x 专属 API, 4.19 上编译必挂 (本轮提前补, 不让它再烧一轮):
#   (a) TWA_RESUME / TWA_NMI_CURRENT: 4.19 的 task_work_add() 第三参是 bool,
#       没有 5.9 引入的 enum task_work_notify_mode。pkg_observer.c 自己定义了,
#       但 allowlist.c / supercall.c 没有 -> 全局补在 linux/task_work.h
#       里 (bool 传 true == notify, 语义等价)。
#   (b) path_umount(): 5.9 才有的导出符号, 4.19 的 fs/namespace.c 只有
#       ksys_umount(char __user *, int)。feature/kernel_umount.c 直接 extern
#       声明了它并在 ksu_umount_mnt() 里调用 -> 链接期 undefined。
#       用 d_path + set_fs(KERNEL_DS) + ksys_umount 做等价实现。
tw = pathlib.Path("include/linux/task_work.h")
if tw.exists():
    t = tw.read_text(errors="ignore")
    if "OPLUS_419_COMPAT_TWA" not in t:
        anchor = "int task_work_add(struct task_struct *task, struct callback_head *twork, bool);"
        block = ("/* OPLUS_419_COMPAT_TWA: 4.19 第三参是 bool, 无 TWA_* 枚举 (5.9+) */\n"
                 "#ifndef TWA_RESUME\n"
                 "#define TWA_RESUME true\n"
                 "#endif\n"
                 "#ifndef TWA_NMI_CURRENT\n"
                 "#define TWA_NMI_CURRENT true\n"
                 "#endif\n\n")
        if anchor in t:
            t = t.replace(anchor, block + anchor, 1)
            tw.write_text(t)
            patched.append("include/linux/task_work.h: TWA_RESUME/TWA_NMI_CURRENT -> true")

ku = pathlib.Path("drivers/kernelsu/feature/kernel_umount.c")
if ku.exists():
    t = ku.read_text(errors="ignore")
    if "OPLUS_419_COMPAT_PATH_UMOUNT" not in t:
        old = ("extern int path_umount(struct path *path, int flags);\n"
               "\n"
               "static void ksu_umount_mnt(const char *mnt, struct path *path, int flags)\n"
               "{\n"
               "    int err = path_umount(path, flags);\n")
        new = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 9, 0)\n"
               "extern int path_umount(struct path *path, int flags);\n"
               "#define ksu_do_path_umount(p, f) path_umount((p), (f))\n"
               "#else\n"
               "/* OPLUS_419_COMPAT_PATH_UMOUNT: 4.19 无 path_umount(), 用\n"
               " * d_path + set_fs(KERNEL_DS) + ksys_umount 做等价实现 */\n"
               "#include <linux/dcache.h>\n"
               "#include <linux/syscalls.h>\n"
               "#include <asm/uaccess.h>\n"
               "static int ksu_do_path_umount(struct path *path, int flags)\n"
               "{\n"
               "    int err;\n"
               "    char *page = (char *)__get_free_page(GFP_KERNEL);\n"
               "    char *name;\n"
               "    mm_segment_t old_fs;\n"
               "\n"
               "    if (!page)\n"
               "        return -ENOMEM;\n"
               "    name = d_path(path, page, PAGE_SIZE);\n"
               "    if (IS_ERR(name)) {\n"
               "        err = PTR_ERR(name);\n"
               "        free_page((unsigned long)page);\n"
               "        return err;\n"
               "    }\n"
               "    old_fs = get_fs();\n"
               "    set_fs(KERNEL_DS);\n"
               "    err = ksys_umount(name, flags);\n"
               "    set_fs(old_fs);\n"
               "    free_page((unsigned long)page);\n"
               "    return err;\n"
               "}\n"
               "#endif\n"
               "\n"
               "static void ksu_umount_mnt(const char *mnt, struct path *path, int flags)\n"
               "{\n"
               "    int err = ksu_do_path_umount(path, flags);\n")
        if old in t:
            t = t.replace(old, new, 1)
            ku.write_text(t)
            patched.append("drivers/kernelsu/feature/kernel_umount.c: path_umount -> ksys_umount 兼容实现")

# 37) drivers/kernelsu/infra/seccomp_cache.c: 该文件重定义了 struct seccomp_filter
#     以便直接 set_bit 内核的 action_cache 位图, 用到的
#       SECCOMP_ARCH_NATIVE_NR / SECCOMP_ARCH_COMPAT_NR / struct action_cache
#     全部是 5.x 才有的 (4.19 的 seccomp_filter 里根本没有 cache 成员)。
#     报错: use of undeclared identifier 'SECCOMP_ARCH_NATIVE_NR'
#     4.19 上这两个 helper 退化为空操作 —— 少一层 seccomp 放行缓存加速而已,
#     功能不受影响 (setuid_hook 里仍会走正常的 seccomp 放行路径)。
#     注意: 不能在 4.19 上照抄其结构体布局, 写错位等于踩内存。
sc = pathlib.Path("drivers/kernelsu/infra/seccomp_cache.c")
if sc.exists():
    t = sc.read_text(errors="ignore")
    if "OPLUS_419_NO_SECCOMP_CACHE" not in t:
        idx = t.find("struct action_cache {")
        if idx > 0:
            head = ("/* OPLUS_419_NO_SECCOMP_CACHE: 4.19 的 struct seccomp_filter 无\n"
                    " * action_cache 成员, 也没有 SECCOMP_ARCH_*_NR; 直接照抄 5.x 布局\n"
                    " * 会写坏内存, 故退化为空操作。 */\n"
                    "#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)\n\n"
                    "void ksu_seccomp_clear_cache(struct seccomp_filter *filter, int nr)\n"
                    "{\n"
                    "    (void)filter;\n"
                    "    (void)nr;\n"
                    "}\n\n"
                    "void ksu_seccomp_allow_cache(struct seccomp_filter *filter, int nr)\n"
                    "{\n"
                    "    (void)filter;\n"
                    "    (void)nr;\n"
                    "}\n\n"
                    "#else\n\n")
            t = t[:idx] + head + t[idx:]
            if not t.endswith("\n"):
                t += "\n"
            t += "\n#endif /* LINUX_VERSION_CODE < 5.0: 无 seccomp action_cache */\n"
            sc.write_text(t)
            patched.append("drivers/kernelsu/infra/seccomp_cache.c: 4.19 退化为空操作")

# 38) include/uapi/linux/mount.h: SukiSU 的 infra/su_mount_ns.c 写
#     #include <uapi/linux/mount.h>, 这个 uapi 头是 5.x 才从 uapi/linux/fs.h
#     拆出来的, 4.19 根本没有 (已核实 404)。
#     报错: fatal error: 'uapi/linux/mount.h' file not found
#     4.19 里 MS_PRIVATE/MS_REC 等挂载标志仍在 uapi/linux/fs.h,
#     CLONE_NEWNS 在 uapi/linux/sched.h -> 建转发头。
um = pathlib.Path("include/uapi/linux/mount.h")
if not um.exists():
    um.parent.mkdir(parents=True, exist_ok=True)
    um.write_text(
        "/* OPLUS_419_UAPI_MOUNT: 4.19 无 uapi/linux/mount.h (5.x 才拆出);\n"
        " * 挂载标志 MS_* 在 4.19 的 uapi/linux/fs.h, CLONE_NEWNS 在 uapi/linux/sched.h */\n"
        "#ifndef _UAPI_LINUX_MOUNT_H\n"
        "#define _UAPI_LINUX_MOUNT_H\n"
        "#include <uapi/linux/types.h>\n"
        "#include <uapi/linux/fs.h>\n"
        "#include <uapi/linux/sched.h>\n"
        "#endif\n"
    )
    patched.append("include/uapi/linux/mount.h: 转发头 -> uapi/linux/fs.h + sched.h (4.19)")

# 39) drivers/kernelsu/infra/su_mount_ns.c: 用了 path_mount(dev, struct path*,
#     type, flags, data) —— 这是 5.9 才有的 API。4.19 的 fs/namespace.c 只有
#     do_mount(const char *dev, const char __user *dir, const char *type,
#              unsigned long flags, void *data), 且未 EXPORT (KSU 编进内核,
#     不受导出限制)。
#     -> 用 d_path + set_fs(KERNEL_DS) 把 path 转成字符串后调 do_mount。
smn = pathlib.Path("drivers/kernelsu/infra/su_mount_ns.c")
if smn.exists():
    t = smn.read_text(errors="ignore")
    if "OPLUS_419_COMPAT_PATH_MOUNT" not in t:
        old = ("extern int path_mount(const char *dev_name, struct path *path, const char *type_page, unsigned long flags,\n"
               "                      void *data_page);\n")
        new = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 9, 0)\n"
               "extern int path_mount(const char *dev_name, struct path *path, const char *type_page, unsigned long flags,\n"
               "                      void *data_page);\n"
               "#else\n"
               "/* OPLUS_419_COMPAT_PATH_MOUNT: 4.19 无 path_mount(), 只有 do_mount()\n"
               " * (第二参是 __user 路径字符串), 故把 struct path 转成绝对路径再调 */\n"
               "#include <linux/dcache.h>\n"
               "#include <asm/uaccess.h>\n"
               "extern long do_mount(const char *dev_name, const char __user *dir_name,\n"
               "                     const char *type_page, unsigned long flags, void *data_page);\n"
               "static int ksu_do_path_mount(const char *dev_name, struct path *path, const char *type_page,\n"
               "                             unsigned long flags, void *data_page)\n"
               "{\n"
               "    int err;\n"
               "    char *page = (char *)__get_free_page(GFP_KERNEL);\n"
               "    char *name;\n"
               "    mm_segment_t old_fs;\n"
               "\n"
               "    if (!page)\n"
               "        return -ENOMEM;\n"
               "    name = d_path(path, page, PAGE_SIZE);\n"
               "    if (IS_ERR(name)) {\n"
               "        err = PTR_ERR(name);\n"
               "        free_page((unsigned long)page);\n"
               "        return err;\n"
               "    }\n"
               "    old_fs = get_fs();\n"
               "    set_fs(KERNEL_DS);\n"
               "    err = do_mount(dev_name, name, type_page, flags, data_page);\n"
               "    set_fs(old_fs);\n"
               "    free_page((unsigned long)page);\n"
               "    return err;\n"
               "}\n"
               "#define path_mount ksu_do_path_mount\n"
               "#endif\n")
        if old in t:
            t = t.replace(old, new, 1)
            smn.write_text(t)
            patched.append("drivers/kernelsu/infra/su_mount_ns.c: path_mount -> do_mount 兼容 (5.9+)")

# 40) drivers/kernelsu/manager/pkg_observer.c: 应用安装监听 (fsnotify) 用的是
#     5.9 才引入的 fsnotify_ops.handle_inode_event, 回调语义与参数完全不同:
#       5.x : int (*handle_inode_event)(struct fsnotify_mark *, u32, inode, dir, qstr *, u32)
#       4.19: int (*handle_event)(struct fsnotify_group *, inode, u32, data, data_type,
#                                 const unsigned char *file_name, u32, iter_info)
#     另外 4.19 没有 5.9 的 FS_MOVE 别名 (只有 FS_MOVED_FROM/FS_MOVED_TO)。
#     做法: 补 FS_MOVE 别名 + 按 4.19 签名移植回调 (文件名优先取 file_name,
#     否则从 data 的 struct path->dentry->d_name 取)。匹配到 packages.list
#     就触发一次已安装应用重扫; 漏触发只是延迟刷新, 不影响 root 功能。
pkg = pathlib.Path("drivers/kernelsu/manager/pkg_observer.c")
if pkg.exists():
    t = pkg.read_text(errors="ignore")
    if "OPLUS_419_COMPAT_FSNOTIFY" not in t:
        # (a) FS_MOVE 别名 (MASK_SYSTEM 在文件开头就要用)
        anchor_a = ("// Older kernels use a boolean task_work notification argument.\n"
                    "#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 8, 0) && !defined(TWA_RESUME)\n"
                    "#define TWA_RESUME true\n"
                    "#endif\n")
        add_a = ("\n/* OPLUS_419_COMPAT_FSNOTIFY: 4.19 只有 FS_MOVED_FROM/FS_MOVED_TO,\n"
                 " * 没有 5.9 引入的 FS_MOVE 组合别名 */\n"
                 "#ifndef FS_MOVE\n"
                 "#define FS_MOVE (FS_MOVED_FROM | FS_MOVED_TO)\n"
                 "#endif\n")
        if anchor_a in t:
            t = t.replace(anchor_a, anchor_a + add_a, 1)
        # (b) fsnotify_ops 按版本分流
        anchor_b = ("static const struct fsnotify_ops ksu_ops = {\n"
                    "    .handle_inode_event = ksu_handle_inode_event,\n"
                    "};\n")
        new_b = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 9, 0)\n"
                 "static const struct fsnotify_ops ksu_ops = {\n"
                 "    .handle_inode_event = ksu_handle_inode_event,\n"
                 "};\n"
                 "#else\n"
                 "/* OPLUS_419_COMPAT_FSNOTIFY: 4.19 的 fsnotify_ops 只有 handle_event,\n"
                 " * 把 5.x 的 handle_inode_event 语义等价移植过来 */\n"
                 "static int ksu_handle_event_419(struct fsnotify_group *group, struct inode *inode, u32 mask,\n"
                 "                                const void *data, int data_type, const unsigned char *file_name,\n"
                 "                                u32 cookie, struct fsnotify_iter_info *iter_info)\n"
                 "{\n"
                 "    const unsigned char *name = file_name;\n"
                 "\n"
                 "    (void)group;\n"
                 "    (void)inode;\n"
                 "    (void)cookie;\n"
                 "    (void)iter_info;\n"
                 "\n"
                 "    if (!name && data_type == FSNOTIFY_EVENT_PATH && data) {\n"
                 "        struct path *p = (struct path *)data;\n"
                 "        if (p->dentry)\n"
                 "            name = (const unsigned char *)p->dentry->d_name.name;\n"
                 "    }\n"
                 "    if (!name)\n"
                 "        return 0;\n"
                 "    if (mask & FS_ISDIR)\n"
                 "        return 0;\n"
                 "    if (!memcmp(name, \"packages.list\", 13) && name[13] == '\\0') {\n"
                 "        pr_info(\"packages.list detected (4.19 compat): %d\\n\", mask);\n"
                 "        ksu_defer_track_throne();\n"
                 "    }\n"
                 "    return 0;\n"
                 "}\n"
                 "\n"
                 "static const struct fsnotify_ops ksu_ops = {\n"
                 "    .handle_event = ksu_handle_event_419,\n"
                 "};\n"
                 "#endif\n")
        if anchor_b in t:
            t = t.replace(anchor_b, new_b, 1)
        pkg.write_text(t)
        patched.append("drivers/kernelsu/manager/pkg_observer.c: fsnotify handle_event 移植 + FS_MOVE 别名")

# 41) 4.19 缺失 API 的兼容 shim
#     SukiSU 是编进 vmlinux 的 (drivers/kernelsu, obj-y), 不受 EXPORT_SYMBOL 限制,
#     所以"未导出"不是问题; 但 5.x 才引入的函数/宏在 4.19 树里连声明都没有,
#     编译期就成了 implicit declaration, 链接期变 undefined symbol.
#     r45 实测暴露:
#       fallthrough                       (5.4 语句)      policy/allowlist.c
#       strscpy_pad                       (5.1 函数)      policy/allowlist.c
#       kvcalloc                          (5.1 inline)    supercall/dispatch.c
#       copy_to_kernel_nofault            (5.8 函数)      hook/arm64/patch_memory.c
#       strncpy_from_user_nofault         (5.8 函数)      sucompat/sulog
#       untagged_addr                     (5.4 宏)        sulog/event.c
#       security_inode_init_security_anon (5.13 函数)     infra/file_wrapper.c
#     同时 bigshot 树自身也有个洞: include/linux/healthinfo/ion.h 声明了
#     ion_total_size / ion_total(), 但树里没有任何实现 -> fs/proc/meminfo.c 引用成隐式声明
def _insert_before_guard_end(rel_path, marker, code_block, probe=None):
    """在 include guard 的最后一个 #endif 之前插入, 避免落到 guard 外面被重复展开

    probe: 若该字符串已存在于目标头文件, 说明这套内核本来就有此符号, 直接跳过.
           (不同 4.19 分支回移程度不同, 必须先查再插, 否则 redefinition)
    """
    p = pathlib.Path(rel_path)
    if not p.exists():
        return False
    t = p.read_text(errors="ignore")
    if marker in t:
        return False
    if probe and probe in t:
        return False
    lines = t.split("\n")
    idx = None
    # 优先落在 __KERNEL__ 块内部 (mm.h 这类头把内核态代码包在 #ifdef __KERNEL__ 里,
    # 插到块外面会让 shim 依赖的 kvmalloc_array 在非内核态上下文里可见性改变)
    for i, l in enumerate(lines):
        if l.lstrip().startswith("#endif") and "__KERNEL__" in l:
            idx = i
            break
    if idx is None:
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].lstrip().startswith("#endif"):
                idx = i
                break
    if idx is None:
        return False
    lines[idx:idx] = code_block.split("\n")
    p.write_text("\n".join(lines))
    return True


SHIMS = [
    # (头文件, 自身标记, 已存在探测串, 代码): 探测串命中说明这棵树本来就有, 跳过
    #
    # !! fallthrough 绝不能做全局宏 (r47 教训) !!
    # 原本在 include/linux/compiler.h 里 #define fallthrough do { } while (0),
    # 结果 net/sctp/sm_make_chunk.c 把 fallthrough 当**标号**用:
    #     goto fallthrough;  /  fallthrough:
    # 宏一展开就变成 goto do { } while (0);  ->  "expected identifier"
    #                                        /  "expected ';' after do/while statement"
    # 4.19 全树扫描后确认: 只有 drivers/kernelsu 内部把它当语句提示用,
    # 所以改成在第 42 步只删 kernelsu 里的 token, 不污染全树。
    ("include/linux/string.h", "OPLUS_419_STRSCPY_PAD", "strscpy_pad(",
     "/* OPLUS 4.19 COMPAT: strscpy_pad 为 5.1 引入 */\n"
     "#ifndef OPLUS_419_STRSCPY_PAD\n"
     "#define OPLUS_419_STRSCPY_PAD\n"
     "static inline ssize_t strscpy_pad(char *dest, const char *src, size_t count)\n"
     "{\n"
     "\tssize_t written = strscpy(dest, src, count);\n"
     "\n"
     "\tif (count > 0) {\n"
     "\t\tsize_t i = written < 0 ? 0 : (size_t)written;\n"
     "\n"
     "\t\tfor (; i < count; i++)\n"
     "\t\t\tdest[i] = '\\0';\n"
     "\t}\n"
     "\treturn written;\n"
     "}\n"
     "#endif\n"),
    # kvcalloc 其实是 4.18 引入, 4.19 通常已有 (bigshot 在 mm.h:3058); 探测串命中就跳过
    ("include/linux/mm.h", "OPLUS_419_KVCALLOC", "kvcalloc(",
     "/* OPLUS 4.19 COMPAT: kvcalloc (4.18+) 缺失时补一份 */\n"
     "#ifndef OPLUS_419_KVCALLOC\n"
     "#define OPLUS_419_KVCALLOC\n"
     "static inline void *kvcalloc(size_t n, size_t size, gfp_t flags)\n"
     "{\n"
     "\treturn kvmalloc_array(n, size, flags | __GFP_ZERO);\n"
     "}\n"
     "#endif\n"),
    ("include/linux/uaccess.h", "OPLUS_419_NOFAULT", "copy_to_kernel_nofault",
     "/* OPLUS 4.19 COMPAT: nofault 系列 (5.8) 与 untagged_addr (5.4) 回落到 4.19 等价实现 */\n"
     "#ifndef OPLUS_419_NOFAULT\n"
     "#define OPLUS_419_NOFAULT\n"
     "#ifndef copy_to_kernel_nofault\n"
     "#define copy_to_kernel_nofault(dst, src, size) probe_kernel_write(dst, src, size)\n"
     "#endif\n"
     "#ifndef strncpy_from_user_nofault\n"
     "#define strncpy_from_user_nofault(dst, src, count) strncpy_from_unsafe_user(dst, src, count)\n"
     "#endif\n"
     "#ifndef untagged_addr\n"
     "#define untagged_addr(addr) (addr)\n"
     "#endif\n"
     "#endif\n"),
]
for _rel, _mark, _probe, _code in SHIMS:
    if _insert_before_guard_end(_rel, _mark, _code, _probe):
        patched.append(f"{_rel}: 4.19 缺失 API shim ({_mark})")
    else:
        print(f"  skip shim {_mark}: {_rel} 已自带或已打过")

# 41b) allowlist.c 用 put_task_struct (4.19 为 sched/task.h 的 static inline)
#      以及 strscpy_pad (shim 在 string.h), 两者都要显式 include 才拿得到
p = pathlib.Path("drivers/kernelsu/policy/allowlist.c")
if p.exists():
    t = p.read_text(errors="ignore")
    changed = False
    if "put_task_struct" in t and "linux/sched/task.h" not in t:
        t = t.replace("#include <linux/kthread.h>",
                      "#include <linux/kthread.h>\n#include <linux/sched/task.h>", 1)
        if "linux/sched/task.h" not in t:
            t = t.replace("#include <linux/rcupdate.h>",
                          "#include <linux/sched/task.h>\n#include <linux/rcupdate.h>", 1)
        changed = True
    if "strscpy_pad" in t and "linux/string.h" not in t:
        t = t.replace("#include <linux/types.h>",
                      "#include <linux/string.h>\n#include <linux/types.h>", 1)
        changed = True
    if changed:
        p.write_text(t)
        patched.append("drivers/kernelsu/policy/allowlist.c: 补 include sched/task.h + string.h")

# 41c) security_inode_init_security_anon 是 5.13 引入, 4.19 直接跳过 anon inode 的 SELinux 初始化
p = pathlib.Path("drivers/kernelsu/infra/file_wrapper.c")
if p.exists():
    t = p.read_text(errors="ignore")
    anchor = "    error = security_inode_init_security_anon(inode, &qname, context_inode);"
    if anchor in t and "OPLUS_419_NO_ANON_SECCTX" not in t:
        repl = ("#ifdef OPLUS_419_NO_ANON_SECCTX\n"
                "    /* 4.19: security_inode_init_security_anon 为 5.13 引入, 跳过 anon inode 的 SELinux 初始化 */\n"
                "    error = 0;\n"
                "    (void)qname;\n"
                "#else\n"
                + anchor + "\n"
                "#endif")
        t = t.replace(anchor, repl, 1)
        # 在文件靠前处定义开关, 让上面的 #ifndef/#else 逻辑成立
        t = t.replace("#include <linux/version.h>",
                      "#include <linux/version.h>\n\n"
                      "#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 13, 0)\n"
                      "#define OPLUS_419_NO_ANON_SECCTX 1\n"
                      "#endif", 1)
        p.write_text(t)
        patched.append("drivers/kernelsu/infra/file_wrapper.c: security_inode_init_security_anon (5.13) 加版本守卫")

# 41d) bigshot 树自身缺口: healthinfo/ion.h 声明了 ion_total_size / ion_total(), 树内无实现
p = pathlib.Path("drivers/staging/android/ion/ion.c")
if p.exists():
    t = p.read_text(errors="ignore")
    if "OPLUS_419_ION_TOTAL_IMPL" not in t:
        t += ("\n/* OPLUS 4.19 COMPAT: include/linux/healthinfo/ion.h 声明了这两个符号,\n"
              " * 但 bigshot 树里只有引用没有实现, fs/proc/meminfo.c 会因此链接失败 */\n"
              "#define OPLUS_419_ION_TOTAL_IMPL 1\n"
              "atomic_long_t ion_total_size = ATOMIC_LONG_INIT(0);\n"
              "unsigned long ion_total(void)\n"
              "{\n"
              "\treturn (unsigned long)atomic_long_read(&ion_total_size);\n"
              "}\n")
        p.write_text(t)
        patched.append("drivers/staging/android/ion/ion.c: 补 ion_total_size / ion_total() 定义")

# 42) fallthrough 语句 (5.4 引入) —— 只删 kernelsu 里的 token, 不做全局宏
#     (见上面 SHIMS 处 r47 教训: net/sctp/sm_make_chunk.c 把它当标号, 全局宏直接炸)
#     该语句在 4.19 上纯属 "抑制 -Wimplicit-fallthrough 告警" 的提示, 删掉不影响语义
_ft = 0
for _p in pathlib.Path("drivers/kernelsu").rglob("*"):
    if _p.suffix not in (".c", ".h"):
        continue
    _t = _p.read_text(errors="ignore")
    _nt = re.sub(r"(?m)^([ \t]*)fallthrough;[ \t]*$",
                 r"\1/* fallthrough: 4.19 无此语句, 已移除 */", _t)
    if _nt != _t:
        _p.write_text(_nt)
        _ft += 1
if _ft:
    patched.append(f"drivers/kernelsu: 移除 {_ft} 个文件的 fallthrough 语句 (避免与 sctp 标号冲突)")

# 43) app_profile.c: 4.19 的 struct seccomp 没有 filter_count, 也没有 seccomp_filter_release
#     本树实测 (include/linux/seccomp.h:28-31):
#         struct seccomp { int mode; struct seccomp_filter *filter; };
#     filter_count 为 v5.0 引入, seccomp_filter_release 为 v5.9 引入;
#     4.19 的等价释放接口是 extern void put_seccomp_filter(struct task_struct *tsk)
#     (kernel/seccomp.c 里做 __put_seccomp_filter(tsk->seccomp.filter)), 语义正好是
#     "把 tsk 当前 filter 的引用计数减一", 与 seccomp_filter_release 的释放部分等价。
p = pathlib.Path("drivers/kernelsu/policy/app_profile.c")
if p.exists():
    t = p.read_text(errors="ignore")
    if "OPLUS_419_SECCOMP" not in t:
        # 43a) filter_count (v5.0)
        old_a = ("    current->seccomp.mode = 0;\n"
                 "    current->seccomp.filter = NULL;\n"
                 "    atomic_set(&current->seccomp.filter_count, 0);\n")
        new_a = ("    current->seccomp.mode = 0;\n"
                 "    current->seccomp.filter = NULL;\n"
                 "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 0, 0)\n"
                 "    atomic_set(&current->seccomp.filter_count, 0);\n"
                 "#endif\n")
        ok_a = old_a in t
        if ok_a:
            t = t.replace(old_a, new_a, 1)

        # 43b) 释放路径 (v5.9): 整块替换为 4.19 的 put_seccomp_filter()
        old_b = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 11, 0)\n"
                 "    // https://github.com/torvalds/linux/commit/bfafe5efa9754ebc991750da0bcca2a6694f3ed3")
        idx = t.find(old_b)
        end_marker = "    seccomp_filter_release(fake);\n    kfree(fake);"
        idx_end = t.find(end_marker)
        ok_b = idx >= 0 and idx_end > idx
        if ok_b:
            block = t[idx:idx_end]
            t = (t[:idx]
                 + "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 9, 0)\n"
                 + block
                 + "    seccomp_filter_release(fake);\n"
                 + "#else\n"
                 + "    /* OPLUS_419_SECCOMP: 4.19 无 seccomp_filter_release, 用等价接口释放\n"
                 + "     * fake 携带的 filter 引用 (前面 memcpy 自 current, filter 已被置空) */\n"
                 + "    put_seccomp_filter(fake);\n"
                 + "#endif\n"
                 + t[idx_end + len("    seccomp_filter_release(fake);\n"):])
        if ok_a or ok_b:
            t = t.replace("#include <linux/seccomp.h>",
                          "#include <linux/seccomp.h>\n"
                          "/* OPLUS_419_SECCOMP: 4.19 struct seccomp 无 filter_count, 无 seccomp_filter_release */", 1)
            p.write_text(t)
            patched.append("drivers/kernelsu/policy/app_profile.c: seccomp filter_count (5.0) / "
                           "seccomp_filter_release (5.9) 加 4.19 等价实现")

# 44) cpu_spoof.c: struct clocksource 的 vdso_clock_mode 成员是 v5.2 才加的
#     4.19 (arch/arm64/include/asm/cacheflush.h 那版树, clocksource.h) 没有该字段,
#     而 vDSO 时钟模式在 4.19 由 arch 层写死为 ARCHTIMER, 根本不需要改写。
#     上面的 vdso_data[CS_*].clock_mode 改写仍然有效 (4.19 有 vdso_data)。
p = pathlib.Path("drivers/kernelsu/extension/cpu_spoof.c")
if p.exists():
    t = p.read_text(errors="ignore")
    old = ("                        (*curr_cs_ptr)->vdso_clock_mode =\n"
           "                            VDSO_CLOCKMODE_ARCHTIMER;\n")
    if "OPLUS_419_CLKSRC_VDSO_MODE" not in t and old in t:
        new = ("#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 2, 0)\n"
               "                        (*curr_cs_ptr)->vdso_clock_mode =\n"
               "                            VDSO_CLOCKMODE_ARCHTIMER;\n"
               "#else\n"
               "                        /* OPLUS_419_CLKSRC_VDSO_MODE: 4.19 struct clocksource\n"
               "                         * 无 vdso_clock_mode (5.2 引入); vDSO 时钟模式由\n"
               "                         * arch 层固定, 无需改写 */\n"
               "                        (void)curr_cs_ptr;\n"
               "#endif\n")
        t = t.replace(old, new, 1)
        p.write_text(t)
        patched.append("drivers/kernelsu/extension/cpu_spoof.c: clocksource->vdso_clock_mode (5.2) 加版本守卫")

# 45) linux/minmax.h (5.10 才从 kernel.h 拆出来) + dispatch.c 缺 sched/task.h
#     r49 预检一次性暴露的两类:
#       sulog/event.c:5        fatal error: 'linux/minmax.h' file not found
#       supercall/dispatch.c   tasklist_lock / init_task 未声明
#     实测 bigshot 4.19: include/linux/sched/task.h:22 `extern rwlock_t tasklist_lock;`
#                        include/linux/sched/task.h:26 `extern struct task_struct init_task;`
#     而 min/max 宏在 4.19 由 include/linux/kernel.h 提供, 建个转发头即可
p = pathlib.Path("include/linux/minmax.h")
if not p.exists():
    p.write_text("/* OPLUS 4.19 COMPAT: linux/minmax.h 是 5.10 从 linux/kernel.h 拆出来的,\n"
                 " * 4.19 的 min()/max()/clamp() 等宏都还在 kernel.h 里, 这里做纯转发。\n"
                 " * (kernel.h 在本树里不反向 include 本文件, 不存在循环) */\n"
                 "#ifndef _LINUX_MINMAX_H\n"
                 "#define _LINUX_MINMAX_H\n"
                 "\n"
                 "#include <linux/kernel.h>\n"
                 "\n"
                 "#endif /* _LINUX_MINMAX_H */\n")
    patched.append("include/linux/minmax.h: 新建转发头 -> linux/kernel.h (5.10 才拆出)")

p = pathlib.Path("drivers/kernelsu/supercall/dispatch.c")
if p.exists():
    t = p.read_text(errors="ignore")
    if "linux/sched/task.h" not in t:
        done = False
        for anchor in ("#include <linux/sched/signal.h>",
                       "#include <linux/sched.h>",
                       "#include <linux/thread_info.h>"):
            if anchor in t:
                t = t.replace(anchor, anchor + "\n#include <linux/sched/task.h>", 1)
                done = True
                break
        if done:
            p.write_text(t)
            patched.append("drivers/kernelsu/supercall/dispatch.c: 补 include linux/sched/task.h "
                           "(tasklist_lock / init_task 的声明处)")

# 46) 4.19 的 SELinux 策略注入层 (最大的一处架构性差异)
#     SukiSU 的 selinux/ 与 feature/selinux_hide.c 全部建立在 5.7+ 架构上:
#        struct selinux_policy  —— 策略是"可替换的指针" selinux_state.policy
#        selinux_state.policy_mutex
#        security_*_with_policy() 一族
#     4.19 里 policydb 内联在 selinux_state.ss 中 (ss/services.h 实测):
#        struct selinux_ss { struct sidtab *sidtab; struct policydb policydb;
#                            rwlock_t policy_rwlock; u32 latest_granting; ... };
#     没有可替换的指针, 也就不存在"复制-改-换指针"的写法, 只能就地修改。
#
#     处理方式 (KernelSU 0.9.5 在 4.14/4.19 上就是这么做的, 已实测):
#       1. sepolicy.c/h 整份换成 0.9.5 的实现 —— 那份是同时兼容 4.14/4.19/5.x 的,
#          ksu_* 函数名/签名与 SukiSU 完全一致 (逐条比对过 19 个符号)
#       2. rules.c 只改两处: apply_kernelsu_rules() 与 handle_sepolicy()
#          的"锁 + 复制策略 + 换指针"包装, 换成 rcu_read_lock + 直接改 ss->policydb,
#          批量协议解析部分原样保留 (ksud 用同一套协议, 不能动)
#       3. feature/selinux_hide.c 不参与编译, 换成空实现 —— 它依赖 *_with_policy
#          与 backup_sepolicy 备份策略, 4.19 无处安放; 且它只是"反检测增强",
#          不是 root 的必要条件
def _kernel_vp():
    t = pathlib.Path("Makefile").read_text(errors="ignore")
    v = int(re.search(r"^VERSION\s*=\s*(\d+)", t, re.M).group(1))
    p = int(re.search(r"^PATCHLEVEL\s*=\s*(\d+)", t, re.M).group(1))
    return (v, p)


_KVP = _kernel_vp()
if _KVP < (5, 7) and pathlib.Path("drivers/kernelsu").is_dir():
    _src = pathlib.Path(__file__).resolve().parent / "compat419"
    _copied = []
    for _dst_rel, _src_name in (
            ("drivers/kernelsu/selinux/rules.c", "rules419.c"),
            ("drivers/kernelsu/selinux/sepolicy.c", "sepolicy419.c"),
            ("drivers/kernelsu/selinux/sepolicy.h", "sepolicy419.h"),
            ("drivers/kernelsu/feature/selinux_hide_stub419.c", "selinux_hide_stub419.c")):
        _s = _src / _src_name
        _d = pathlib.Path(_dst_rel)
        if _s.is_file() and _d.parent.is_dir():
            _d.write_bytes(_s.read_bytes())
            _copied.append(_dst_rel)
    # Kbuild: 用空实现顶掉 selinux_hide.o
    _kb = pathlib.Path("drivers/kernelsu/Kbuild")
    if _kb.exists():
        _t = _kb.read_text(errors="ignore")
        if "feature/selinux_hide.o" in _t:
            _t = _t.replace("feature/selinux_hide.o", "feature/selinux_hide_stub419.o")
            _kb.write_text(_t)
            _copied.append("Kbuild: selinux_hide.o -> selinux_hide_stub419.o")
    if _copied:
        patched.append("4.19 SELinux 层替换 (%d.%d < 5.7): %s"
                       % (_KVP[0], _KVP[1], ", ".join(_copied)))

# 41e) fs/proc/meminfo.c 引用 ion_total 未 include 声明头
p = pathlib.Path("fs/proc/meminfo.c")
if p.exists():
    t = p.read_text(errors="ignore")
    if "ion_total" in t and "healthinfo/ion.h" not in t:
        t = t.replace("#include <linux/swap.h>",
                      "#include <linux/swap.h>\n#include <linux/healthinfo/ion.h>", 1)
        p.write_text(t)
        patched.append("fs/proc/meminfo.c: 补 include <linux/healthinfo/ion.h>")

for line in patched:
    print(f"  patched: {line}")
print("file patches done")
