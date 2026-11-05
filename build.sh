#!/usr/bin/env bash
# Realme GT Neo 2 (bitra) 内核编译脚本
# 源码: realme 官方 Android T (4.19.157) 内核源码
# Root: SukiSU-Ultra (main / kprobe hook) + SusFS 隐藏
# 工具链: proton-clang (与社区已验证的 bitra 内核一致)
set -euo pipefail

DEFCONFIG="${1:?usage: build.sh <defconfig> [tag]}"
TAG="${2:-kernel}"
ORIGINAL="$PWD"
JOBS=$(nproc --all)
if [ "${SKIP_SU:-0}" = "1" ]; then SUFFIX="stock"; else SUFFIX="SukiSU-susfs"; fi

KERNEL_URL="https://github.com/Blackmanx/kernel_realme_sm8250"
# r42: 换底座。原 realme 官方 AndroidT 树里 fs/oext4、fs/erofs、fs/exfat、
# drivers/soc/oplus、include/soc/oplus、net/oplus_modules 全是指向未开源
# vendor/oplus/kernel_4.19/ 的失效符号链接, 需要 fs_restore + bitra 回填 +
# kconfig 占位三套补丁才能凑齐一个完整源码树。
# Blackmanx/kernel_realme_sm8250 是同设备社区的完整化分支 (苓茶内核就用它),
# 上述目录全是真实源码, 且已验证可开机。分支 bigshot = 骁龙870 (GT Neo 2 /
# 大师探索版) 在 Android 13 底包上的那一支。
KERNEL_BRANCH="bigshot"
SUSFS_URL="https://gitlab.com/simonpunk/susfs4ksu"

# === 底座类型开关 (r44 核心) ===
# 两套底座对补丁的需求完全相反, 必须分流, 否则会互相破坏:
#
# official (realme 官方树): 大量目录是指向未开源 vendor/oplus/kernel_4.19 的失效符号链接。
#   必须"删宏/改名/补源码/注释 include", 让引用闭源实现的代码整体编译跳过。
#
# community (bigshot 这类完整化树): 所有实现都是真实源码, 而那些 OPLUS_FEATURE_* 宏
#   是"承重"的 —— 它们不只控制代码开关, 还改结构体布局:
#     include/linux/sched.h:1573  #ifdef OPLUS_FEATURE_SCHED_ASSIST
#                                     int ux_state;   <-- 宏被删, struct task_struct 就少字段
#   而 kernel/sched_assist/ 又是 obj-y 无条件编译。删宏的直接后果:
#     sched_assist_common.h:264: error: no member named 'ux_state' in 'struct task_struct'
#   即使侥幸编过, 原厂 vendor 模块按官方布局访问 task_struct 也会错位 —— 这正是
#   刷完卡 logo 的典型成因。所以 community 树一个宏都不许动。
case "$KERNEL_URL" in
  *Blackmanx*|*community*) TREE_FLAVOR="community" ;;
  *)                       TREE_FLAVOR="official"  ;;
esac
echo "==> 底座类型: $TREE_FLAVOR ($KERNEL_URL @ $KERNEL_BRANCH)"

export KBUILD_BUILD_USER="SukiSU"
export KBUILD_BUILD_HOST="gtneo2"
export KBUILD_BUILD_TIMESTAMP="Thu Jan 1 00:00:00 UTC 2026"

mkdir -p "$ORIGINAL/out"

KSU_CONFIG_OPTS=(
  KSU
  KSU_SUSFS
  KSU_SUSFS_HAS_MAGIC_MOUNT
  KSU_SUSFS_SUS_PATH
  KSU_SUSFS_SUS_MOUNT
  KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
  KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
  KSU_SUSFS_SUS_KSTAT
  KSU_SUSFS_TRY_UMOUNT
  KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT
  KSU_SUSFS_SPOOF_UNAME
  KSU_SUSFS_ENABLE_LOG
  KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
  KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
  KSU_SUSFS_OPEN_REDIRECT
  KPROBES
  KPROBE_EVENTS
  KRETPROBES
  EXT4_FS
  TMPFS_XATTR
  TMPFS_POSIX_ACL
)

configure_kernel() {
  mkdir -p out
  # === 基线选择 (r34 核心修复) ===
  # 原厂内核开了 CONFIG_IKCONFIG, 其 .config 以 gzip 形式内嵌在 Image 里。
  # 从用户原厂 boot.img 提取出 5504 项真实配置 (stock.config), 与源码里的
  # vendor/kona-perf_defconfig 相比有 234 项差异 —— 其中 130 项是原厂真实开启
  # 而我们全部丢失的 OPLUS_*(64)/TOUCHPANEL_*(18) 等功能。用 defconfig 当基线
  # 等于凭空造一个和原厂功能集不同的内核, vendor 模块按原厂结构体布局访问会错位。
  # 现在直接用原厂实测配置当基线, olddefconfig 会自动丢弃本源码树不存在的符号
  # (未开源的组件) 并补齐 SukiSU/SusFS 新增项。
  if [ -f "$ORIGINAL/stock.config" ]; then
    echo "  --> 基线: 原厂实测 stock.config (从原厂内核 IKCONFIG 提取)"
    cp "$ORIGINAL/stock.config" out/.config
    make O=out ARCH=arm64 SUBARCH=arm64 olddefconfig
  else
    echo "  --> 基线: $DEFCONFIG (!! 与原厂实际配置存在数百项漂移)"
    make O=out ARCH=arm64 SUBARCH=arm64 "$DEFCONFIG"
  fi
  for opt in "${KSU_CONFIG_OPTS[@]}"; do
    ./scripts/config --file out/.config -e "$opt" || true
  done
  ./scripts/config --file out/.config -d KSU_SUSFS_SUS_SU || true
  # STMVL53L1 (ST ToF 激光对焦传感器) 在 Kconfig 里 default y, 但其 CCI 接口
  # 依赖未开源的 camera techpack 头文件 (cam_cci_ctrl_interface.h);
  # GT Neo 2 无此硬件, 显式禁用 (defconfig 显式 not-set 可覆盖 default y)
  ./scripts/config --file out/.config -d STMVL53L1 || true
  # OPLUS_ION_BOOSTPOOL (ION 内存加速池): Kconfig default n, 但 vendor defconfig
  # 第1148行显式 =y。其头/源文件 (oplus_ion_boost_pool.h/.c) 是指向未开源 vendor
  # 的失效符号链接 (bitra 也未补全该组件) —— 禁用后 ion_system_heap.c 走各处
  # #ifndef 路径 (stock CAF 行为), 功能为标准 ION 分配
  ./scripts/config --file out/.config -d OPLUS_ION_BOOSTPOOL || true
  # OPLUS_SECURE_GUARD (oplus 安全 syscall/exec/mount 钩子): 其实现
  # oplus_invoke_syscall/oplus_exec_block/oplus_mount_block 闭源未发布,
  # 关闭后走各调用点 #else 的 stock CAF 路径
  ./scripts/config --file out/.config -d OPLUS_SECURE_GUARD || true
  # OPLUS_UX_IM_FLAG (给 IM/即时通讯线程打 UX 标记的 proc 节点): 其代码
  # (kernel/sched_assist/sched_assist_common.c 的 im_flag_set_handle 等) 直接读写
  # task->ux_im_flag, 而 include/linux/sched.h 里根本没有这个字段 —— 官方树的
  # sched.h 也没有(两边都是 2407 行, 同样缺), 说明这是 bigshot 那份 5.4 代码搬进
  # 4.19 时留下的洞。原厂配置把它打开了, 于是 6 处引用全部编译失败。
  # 关掉后整块 #ifdef CONFIG_OPLUS_UX_IM_FLAG 编译跳过, 只失去一个 IM 线程标记节点。
  ./scripts/config --file out/.config -d OPLUS_UX_IM_FLAG || true
  # === MODVERSIONS 关闭 + vermagic 强制带 modversions (r33) ===
  # 矛盾点: 原厂模块 vermagic 含 "modversions", 内核不带该标志则全部模块被拒载;
  # 但开启 MODVERSIONS 会触发官方源码缺陷:
  #   WARNING: EXPORT symbol "gsi_write_channel_scratch" version generation failed
  #   ld.lld: relocation R_AARCH64_ABS32 cannot be used against symbol
  #           '__crc_gsi_write_channel_scratch'; recompile with -fPIC
  # (genksyms 解析不了该符号类型 -> __crc_ 未定义 -> vmlinux 链接必死)
  # 解法: CONFIG_MODVERSIONS=n 绕开 CRC 机制 (不改变 struct module 布局),
  #       再用 fix_file_patches 第31步把 "modversions " 硬写进 VERMAGIC_STRING。
  #       模块加载时因 MODVERSIONS=n 不做 CRC 校验, 只比对 vermagic 字符串。
  ./scripts/config --file out/.config -d MODVERSIONS || true
  # === 关闭模块签名强制校验 (保留 CONFIG_MODULE_SIG=y 以维持 struct module 布局,
  #     否则 module_layout 的 CRC 变更同样会让原厂模块拒载) ===
  # 我们没有 realme 的签名私钥, MODULE_SIG_FORCE=y 会拒绝加载所有原厂 vendor 模块。
  ./scripts/config --file out/.config -e MODULE_SIG || true
  ./scripts/config --file out/.config -d MODULE_SIG_FORCE || true
  make O=out ARCH=arm64 olddefconfig

  # === 硬性断言 (r34) ===
  # 之前三轮都出现过"编译通过、产物看起来正常、刷进去却卡开机 logo"的情况,
  # 根因是 Kconfig 里符号根本不存在导致配置被静默丢弃 (ext4/erofs 就是这样丢的)。
  # 这里在编译前就把必需项钉死, 缺一个直接失败, 不再产出开不了机的内核。
  python3 - out/.config <<'PY'
import re, sys

cfg = {}
for line in open(sys.argv[1], errors='ignore'):
    line = line.strip()
    m = re.match(r'^(CONFIG_[A-Z0-9_]+)=(.*)$', line)
    if m:
        cfg[m.group(1)] = m.group(2)

must_y = [
    ('CONFIG_EXT4_FS', 'ext4: /metadata 走 first_stage_mount, 缺失则第一阶段 init 卡死'),
    ('CONFIG_JBD2', 'ext4 日志层'),
    ('CONFIG_EROFS_FS', 'system/vendor 等只读分区可能为 erofs'),
    ('CONFIG_EROFS_FS_ZIP', 'erofs 压缩镜像支持'),
    ('CONFIG_F2FS_FS', '/data 分区'),
    ('CONFIG_FS_ENCRYPTION', '/data 文件级加密 (FBE)'),
    ('CONFIG_EXFAT_FS', '原厂启用, 外接存储'),
    ('CONFIG_TMPFS', 'init 根文件系统'),
    ('CONFIG_BLK_DEV_INITRD', 'ramdisk 引导'),
    ('CONFIG_MODULES', '加载原厂 vendor 模块'),
    ('CONFIG_MODULE_SIG', '维持 struct module 布局 (不能关)'),
]
must_n = [
    ('CONFIG_MODULE_SIG_FORCE', '无真我签名私钥, 强制校验会拒载全部原厂模块'),
    ('CONFIG_MODVERSIONS', '官方源码 genksyms 缺陷, 改由 vermagic 硬写补标志'),
]
su_items = ['CONFIG_KSU', 'CONFIG_KSU_SUSFS']

bad = []
for k, why in must_y:
    v = cfg.get(k)
    if v != 'y':
        bad.append('%s = %s  (应为 y; %s)' % (k, v if v is not None else '<符号不存在>', why))
for k, why in must_n:
    v = cfg.get(k)
    if v not in (None, 'n'):
        bad.append('%s = %s  (应为 n; %s)' % (k, v, why))

print('  --- 关键配置核对 ---')
for k, _ in must_y:
    print('    %-28s = %s' % (k, cfg.get(k, '<缺失>')))
for k, _ in must_n:
    print('    %-28s = %s' % (k, cfg.get(k, '<缺失>')))
for k in su_items:
    print('    %-28s = %s' % (k, cfg.get(k, '<缺失>')))

if bad:
    print('FATAL: 配置断言失败, 该内核必然无法开机:')
    for b in bad:
        print('   - ' + b)
    sys.exit(1)
print('  OK: 文件系统与模块配置齐全')
PY
}

echo "==> [1/7] 拉取内核源码 ($KERNEL_BRANCH 分支, kernel 4.19.157)..."
# 预清理 (绝对路径; 保留仓库自带 ak3/ 模板目录!)
rm -rf kernel out "$ORIGINAL/susfs" "$ORIGINAL/ak3-clone" "$ORIGINAL/bitra-ref"
# 多源回退: 直连 -> 镜像加速 (VM/弱网环境 github 直连常被 reset)
KERNEL_URLS=("$KERNEL_URL"
  "https://gh-proxy.com/$KERNEL_URL"
  "https://ghproxy.net/$KERNEL_URL"
  "https://gitclone.com/github.com/Blackmanx/kernel_realme_sm8250")
CLONE_OK=""
for i in 1 2 3 4 5 6; do
  u="${KERNEL_URLS[$(( (i-1) % ${#KERNEL_URLS[@]} ))]}"
  echo "  clone 尝试 $i: $u (-b $KERNEL_BRANCH)"
  if git clone --depth=1 -b "$KERNEL_BRANCH" "$u" kernel; then CLONE_OK="yes"; break; fi
  rm -rf kernel
  sleep 10
done
[ -n "$CLONE_OK" ] || { echo "FATAL: kernel 源码拉取失败"; exit 1; }
cd kernel

# Oplus Makefile 用 Python2 语法写的 gcc-wrapper.py 包裹编译器，新系统无 python2 会直接报错
# 摘掉包装，保留其内部 REAL_CC 逻辑
sed -i 's|$(PYTHON) $(srctree)/scripts/gcc-wrapper.py ||' Makefile
grep -n "^CC" Makefile 2>/dev/null | head -3 || true

# OplusKernelEnvConfig.mk 白名单宏会激活引用闭源头文件的核心代码:
#   - SCHED_ASSIST -> mutex.h 闭源调度
#   - VIRTUAL_RESERVE_MEMORY -> linux/reserve_area.h + fs/proc/va_feature_node.h (均未开源)
#   - TASK_CPUSTATS -> account_task_time/fs/proc/task_cpustats (闭源; defconfig 里
#     #ifdef 包 CONFIG 行无效, CONFIG_OPLUS_CTP/SCHED 实际从未开启)
#   - HEALTHINFO -> ion_total()/linux/healthinfo/* (闭源)
#     且官方 defconfig 本就未开启 CONFIG_VIRTUAL_RESERVE_MEMORY, 出厂编译时该特性守卫即为 false
# 中和这些宏 = 整个功能编译跳过, 与官方出厂行为一致
# !! 注意: 必须"改名", 不能"删行" (r42 教训) !!
# 官方源码树里这些符号只出现在 ALLOWED_MCROS 列表中, 所以 `/符号/d` 删行没问题;
# 但第三方树里同一个符号还出现在 `ifeq ($(OPLUS_FEATURE_X),yes)` 判断里,
# 删行会把 ifeq 行一起删掉, 只剩下面的 endif -> make 直接报
#   OplusKernelEnvConfig.mk:208: *** extraneous 'endif'.  Stop.
# 改名方案对两种出现位置都安全, 且逐行结构完全不变:
#   列表项   -> 生成 -DOPLUS_DISABLED_xxx (无人引用, 无害)
#   ifeq 判断 -> 变量永未定义, 条件恒假, 整块跳过
#
# !! 但 community 树一律不许动 (r43 教训) !! 那套树里宏是承重的, 见上面 TREE_FLAVOR 注释
if [ "$TREE_FLAVOR" = "official" ]; then
for _m in SCHED_ASSIST MULTI_FREEAREA PROCESS_RECLAIM VIRTUAL_RESERVE_MEMORY TASK_CPUSTATS HEALTHINFO; do
  sed -i "s/OPLUS_FEATURE_${_m}/OPLUS_DISABLED_${_m}/g" OplusKernelEnvConfig.mk
done
# SECURE_GUARD/MOUNTGUARD/EXECGUARD 三个 ifeq 块强制 export CONFIG_OPLUS_*_GUARD=y
# 并加 -D 命令行宏 (优先级高于 .config, scripts/config -d 无法关闭):
#   CONFIG_OPLUS_SECURE_GUARD  -> oplus_invoke_syscall (闭源)
#   CONFIG_OPLUS_MOUNT_BLOCK   -> oplus_mount_block    (闭源)
#   CONFIG_OPLUS_EXECVE_*      -> oplus_exec_block     (闭源)
# 删除强制注入行后, 调用点 #ifdef 自动落到 stock CAF 路径 (bitra 同做法: 整块删除)
sed -i -e '/export CONFIG_OPLUS_SECURE_GUARD/d'  -e '/DCONFIG_OPLUS_SECURE_GUARD/d' \
       -e '/export CONFIG_OPLUS_MOUNT_BLOCK/d'   -e '/DCONFIG_OPLUS_MOUNT_BLOCK/d' \
       -e '/export CONFIG_OPLUS_EXECVE_BLOCK/d'  -e '/DCONFIG_OPLUS_EXECVE_BLOCK/d' \
       -e '/DCONFIG_OPLUS_EXECVE_REPORT/d' OplusKernelEnvConfig.mk
echo "OplusKernelEnvConfig.mk: official 树 -> 6 个闭源特性宏已改名中和, SECURE_GUARD/MOUNT_BLOCK/EXECVE 强制注入行已删"
else
echo "OplusKernelEnvConfig.mk: community 树 -> 保持原样 (宏改结构体布局, 动了反而炸)"
fi
# 结构自检: make 的条件指令一旦不平衡就直接 "extraneous 'endif'", 报错位置飘忽难查,
# 这里提前拦一道, 让失败信息指向真正的修改脚本而不是 make 的某一行
python3 - <<'PYCHK' || exit 1
import sys
lines = open('OplusKernelEnvConfig.mk', encoding='utf-8', errors='replace').read().split('\n')
depth = 0
for i, l in enumerate(lines, 1):
    s = l.strip()
    if s.startswith(('ifeq', 'ifneq', 'ifdef', 'ifndef')):
        depth += 1
    elif s.startswith('endif'):
        depth -= 1
        if depth < 0:
            print("FATAL: OplusKernelEnvConfig.mk 第 %d 行出现孤立 endif (补丁删行过头)" % i)
            sys.exit(1)
print("  OplusKernelEnvConfig.mk 条件块配平 OK (depth=%d)" % depth)
PYCHK

# SKIP_SU=1 时跳过 SukiSU/SusFS, 产出纯净对照内核 (用于定位卡 logo 是否由 rootkit 引起)
if [ "${SKIP_SU:-0}" = "1" ]; then
  echo "==> [2/7][3/7] SKIP_SU=1: 跳过 SukiSU/SusFS, 构建纯净对照版"
else

echo "==> [2/7] 集成 SukiSU-Ultra (main 分支, kprobe hook)..."
SU_BASES=("https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/main/kernel/setup.sh"
  "https://gh-proxy.com/https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/main/kernel/setup.sh"
  "https://ghproxy.net/https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/main/kernel/setup.sh")
for i in 1 2 3 4 5 6; do
  b="${SU_BASES[$(( (i-1) % ${#SU_BASES[@]} ))]}"
  echo "  setup.sh 尝试 $i: $b"
  if curl -LSs --retry 3 --retry-delay 5 --retry-all-errors "$b" | bash -s main; then break; fi
  echo "!! setup.sh 拉取失败 (第 $i 次)，重试..."
  sleep 10
done
[ -d drivers/kernelsu ] || { echo "FATAL: SukiSU 集成失败"; exit 1; }

echo "==> [3/7] 应用 SusFS 补丁 (kernel-4.19 分支)..."
for i in 1 2 3 4 5; do
  git clone --depth=1 -b kernel-4.19 "$SUSFS_URL" ../susfs && break
  echo "!! susfs clone 失败 (第 $i 次)，重试..."
  rm -rf ../susfs
  sleep 10
done
[ -d ../susfs ] || { echo "FATAL: susfs 仓库拉取失败"; exit 1; }
patch -p1 --forward < ../susfs/kernel_patches/50_add_susfs_in_kernel-4.19.patch \
  || echo "!! 部分 hunk 已应用或失败，继续检查核心文件..."
# 兜底：确保 susfs 核心文件就位
cp -f ../susfs/kernel_patches/fs/susfs.c fs/ 2>/dev/null || true
cp -f ../susfs/kernel_patches/include/linux/susfs.h include/linux/ 2>/dev/null || true
cp -f ../susfs/kernel_patches/include/linux/susfs_def.h include/linux/ 2>/dev/null || true
ls fs/susfs.c include/linux/susfs.h

fi   # SKIP_SU 只跳过 rootkit 本体, 3b 之后的 Kconfig/回填/治愈补丁仍然必须执行

echo "==> [3b] Kconfig 占位修复 (Oplus 发布源码缺失的 Kconfig 文件)..."
python3 "$ORIGINAL/kconfig_stubs.py" || echo "!! 占位脚本异常，继续构建"

# === [3b2] 必须紧跟在 kconfig_stubs 之后 ===
# kconfig_stubs 会把 fs/oext4、fs/erofs、fs/exfat 三个失效符号链接重建成空目录,
# 导致 CONFIG_EXT4_FS/EROFS_FS/EXFAT_FS 三个符号在 Kconfig 里消失 -> 配置被静默丢弃
# -> 内核没有 ext4/erofs -> /metadata(first_stage_mount) 挂不上 -> 卡开机 logo。
# 用 realme 同厂商 AndroidR 源码仓库里完整发布的这三个目录覆盖回来。
echo "==> [3b2] 补回未开源的文件系统组件 (oext4/erofs/exfat)..."
python3 "$ORIGINAL/fs_restore.py" "$ORIGINAL/fs_vendor.zip" || { echo "FATAL: 文件系统组件补全失败"; exit 1; }

if [ "${SKIP_SU:-0}" = "1" ]; then
  echo "==> [3c] SKIP_SU=1: 跳过 susfs 适配补丁与 KSU_SUSFS Kconfig 注入"
else
echo "==> [3c] 应用 susfs realme 适配补丁 (官方 hunk 不兼容 Oplus 源码的 5 处)..."
python3 "$ORIGINAL/fix_susfs.py" || echo "!! susfs 适配脚本异常，继续构建"

echo "==> [3c1] 注入 KSU_SUSFS Kconfig 定义 (SukiSU main 不自带, 缺失则 susfs 全部静默失效)..."
python3 "$ORIGINAL/susfs_kconfig.py" || { echo "FATAL: KSU_SUSFS Kconfig 注入/自检失败"; exit 1; }
fi

echo "==> [3c2] 从社区 bitra 内核回填 Oplus 闭源组件 (system/device_info/sensor/thermal)..."
# realme 官方源码 drivers/soc/oplus/{system,device_info,sensor,thermal} 和 include/soc/oplus
# 全部指向未开源 vendor 目录 (失效符号链接)。ProjectElixir bitra 内核 (同设备, 已验证可编译)
# 补全了这些组件 —— 直接回填, 让 oplus_project.h 等头文件及其实现恢复存在
if [ -f include/soc/oplus/system/oplus_project.h ] && [ -d drivers/soc/oplus/system ]; then
  echo "==> [3c2] 跳过 bitra 回填: 本底座已含完整 Oplus 闭源组件 (oplus_project.h 存在)"
else
BITRA_URL="https://github.com/ProjectElixir-Devices/kernel_realme_sm8250-bitra"
for i in 1 2 3 4 5 6; do
  case $(( (i-1) % 3 )) in
    0) u="$BITRA_URL" ;;
    1) u="https://gh-proxy.com/$BITRA_URL" ;;
    2) u="https://gitclone.com/github.com/ProjectElixir-Devices/kernel_realme_sm8250-bitra" ;;
  esac
  echo "  bitra-ref 尝试 $i: $u"
  if git clone --depth=1 -b bigshot-AOSP "$u" ../bitra-ref; then break; fi
  echo "!! bitra-ref clone 失败 (第 $i 次)，重试..."
  rm -rf ../bitra-ref
  sleep 10
done
if [ -d ../bitra-ref ]; then
  # 整体替换 include/soc/oplus (占位脚本可能已把其中符号链接重建为空文件, 必须先删干净)
  rm -rf include/soc/oplus
  mkdir -p include/soc/oplus
  cp -rf ../bitra-ref/include/soc/oplus/. include/soc/oplus/
  echo "  restored: include/soc/oplus/"
  for d in system device_info sensor thermal; do
    if [ -d "../bitra-ref/drivers/soc/oplus/$d" ]; then
      rm -rf "drivers/soc/oplus/$d"
      cp -r "../bitra-ref/drivers/soc/oplus/$d" "drivers/soc/oplus/$d"
      echo "  restored: drivers/soc/oplus/$d"
    fi
  done
  # 回填 include/linux 下的 Oplus 闭源头文件/目录 (官方源码中全是失效符号链接)
  for h in process_mm_reclaim.h vm_anti_fragment.h task_sched_info.h cpu_jank_info.h \
           reserve_area.h lowmem_dbg.h oplus_wakelock_profiler.h device_info.h; do
    if [ -f "../bitra-ref/include/linux/$h" ]; then
      cp -f "../bitra-ref/include/linux/$h" "include/linux/$h"
      echo "  restored: include/linux/$h"
    fi
  done
  for d in healthinfo iomonitor im special_opt tpd; do
    if [ -d "../bitra-ref/include/linux/$d" ]; then
      rm -rf "include/linux/$d"
      cp -r "../bitra-ref/include/linux/$d" "include/linux/$d"
      echo "  restored: include/linux/$d/"
    fi
  done
  [ -f include/soc/oplus/system/oplus_project.h ] || echo "!! 警告: oplus_project.h 回填失败, 后续编译可能报缺失"
else
  echo "!! bitra-ref 不可用，缺失组件按空 stub 处理"
fi
fi   # 底座自带完整 Oplus 组件时跳过上面整段回填

if [ "$TREE_FLAVOR" = "official" ]; then
echo "==> [3d] 自动扫描缺失头文件的 include, 删除对应 OPLUS 白名单宏..."
python3 "$ORIGINAL/fix_oplus_macros.py" || echo "!! 宏清理脚本异常，继续构建"
else
# community 树: 头文件与实现都是真实源码, 删宏只会破坏结构体布局 (r43 教训)
echo "==> [3d] community 树: 跳过宏清理 (所有 OPLUS 特性实现均为真实源码)"
fi

echo "==> [3d2] 文件级修补 (SukiSU/SusFS 4.19 适配 + 闭源符号兜底)..."
python3 "$ORIGINAL/fix_file_patches.py" || echo "!! 文件修补脚本异常，继续构建"

echo "==> [4/7] 拉取 Neutron Clang 工具链 (proton-clang 过老，ld 无法链接新 glibc)..."
mkdir -p "$PWD/neutron-clang" && cd "$PWD/neutron-clang"
for i in 1 2 3 4 5; do
  curl -LOs --retry 5 --retry-delay 5 --retry-all-errors \
    "https://raw.githubusercontent.com/Neutron-Toolchains/antman/main/antman" && break
  echo "!! antman 拉取失败 (第 $i 次)，重试..."
  sleep 10
done
chmod +x antman
./antman -S=latest
cd - > /dev/null
export PATH="$PWD/neutron-clang/bin:$PATH"
clang --version | head -1

echo "==> [4b] 全局移除 -Werror (Oplus 源码按 GCC 旧告警标准编写, Clang 严格告警全变错误;
#        显式 -Werror=xxx 不受 KCFLAGS -Wno-error 影响, 必须从 Makefile 源头剥离)..."
grep -rlZ --include='Makefile' --include='Makefile.*' --include='Kbuild*' -e '-Werror' . 2>/dev/null \
  | xargs -0 -r sed -i 's/-Werror[=-][a-zA-Z0-9_=.-]*//g; s/-Werror//g'
echo "  -Werror stripped from $( (grep -rl --include='Makefile*' --include='Kbuild*' -e '-Werror' . 2>/dev/null || true) | wc -l) remaining files"

echo "==> [5/7] 配置内核: $DEFCONFIG..."
configure_kernel

BUILD_FLAGS=(O=out ARCH=arm64 SUBARCH=arm64
  CC=clang AR=llvm-ar NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip
  LLVM=1 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_ARM32=arm-linux-gnueabi-
  # Oplus 源码按 GCC 习惯留有 implicit-int/隐式声明等历史问题 (出厂用 GCC 只告警),
  # Clang -Werror 会全部升级为错误 —— 全局降级, 真正的链接错误仍会正常失败
  KCFLAGS="-Wno-error")

echo "==> [5b] SukiSU 子树快速预检 (只编 drivers/kernelsu, -k 一次暴露全部错误)..."
# 痛点: 全量编译 15 分钟, 但 make 遇错即停, 每轮只能暴露 1 个错误,
# 而 4.19 缺的 API/结构体成员是一个一个冒出来的 (已经连修 18 处)。
# drivers/kernelsu 是唯一反复重建的子树, 单独用 -k 编一遍只需 1~2 分钟,
# 而且能把该子树里所有编译错误一次性打出来, 不必每轮等 15 分钟。
set +e
# 先编 security/selinux: 它会在编译过程中生成 security/selinux/flask.h 等头文件,
# kernelsu 里 include 的 objsec.h/security.h 都依赖它。全量编译时顺序天然满足,
# 单独编子树时 flask.h 还不存在 → r49 预检里刷了一片假的 'flask.h not found'。
make "${BUILD_FLAGS[@]}" -j"$JOBS" security/selinux/ > /tmp/sel_pre.log 2>&1
SEL_RC=$?
make "${BUILD_FLAGS[@]}" -j"$JOBS" -k drivers/kernelsu/ > /tmp/ksu_pre.log 2>&1
KSU_PRE_RC=$?
set -e
echo "  预检结果: selinux exit=$SEL_RC(仅用于生成 flask.h), kernelsu exit=$KSU_PRE_RC"
# 注意: 本脚本是 set -euo pipefail。grep 无匹配时退出码 1, 经 pipefail 会传染整条
# 流水线 → 一次"零错误"的成功预检反而让脚本 exit 1 (r52 就这么被误判成失败)。
# 必须用 ( ... || true ) 把中间的 grep 归一化。
KSU_ERR=$( (grep -E " error: | fatal error: " /tmp/ksu_pre.log | grep -v Werror || true) | wc -l )
if [ "$KSU_ERR" -gt 0 ]; then
  echo "!! drivers/kernelsu 存在编译错误, 完整清单:"
  (grep -E " error: | fatal error: " /tmp/ksu_pre.log | grep -v Werror | sed 's/^/    /' | head -40) || true
  echo "FATAL: 先修完上面这些再进全量编译 (不浪费 15 分钟)"
  exit 1
fi
echo "  OK: drivers/kernelsu 全部目标编过"

echo "==> [6/7] 编译裸 Image (jobs=$JOBS, GNU as —— 4.19 老内核不兼容 LLVM 集成汇编器)..."


# 只编 Image (未压缩). 原厂 boot.img 实测 KERNEL_FMT=raw, 47MB 未压缩且内核尾部
# 无内嵌 FDT; 设备树走 boot 镜像里独立的 15.8MB dtb 段 (magiskboot 重打包时原样保留)。
# 之前发 Image.gz-dtb 是 r32 卡 logo 的根因之二: realme abl 不解压 gzip kernel。
if ! make "${BUILD_FLAGS[@]}" -j"$JOBS" Image; then
  echo "!! 编译失败，清理后重试一次..."
  rm -rf out
  configure_kernel
  make "${BUILD_FLAGS[@]}" -j"$JOBS" Image
fi

echo "==> [7/7] 打包裸 Image 与 AnyKernel3 卡刷包..."
BOOT="$PWD/out/arch/arm64/boot"
ls -lh "$BOOT/Image"
python3 - "$BOOT/Image" <<'PY'
import sys
d = open(sys.argv[1], 'rb').read()
assert d[0x38:0x3c] == b'ARM\x64', 'FATAL: 不是标准 ARM64 Image'
assert d.rfind(b'\xd0\x0d\xfe\xed') < 0, 'FATAL: Image 内部混入了 dtb'
print('  Image 校验通过: %d 字节 (%.1f MB), ARM64 魔数 OK, 无内嵌 dtb'
      % (len(d), len(d) / 1048576))
PY

# --- vermagic 逐字校验: 必须与 /vendor/lib/modules/*.ko 的 vermagic 完全一致,
#     否则所有原厂 vendor 模块 (触摸/显示/WLAN/音频/相机) 全部拒载 -> 卡 logo ---
echo "  --- vermagic 检查 ---"
grep -E '^CONFIG_(LOCALVERSION|MODVERSIONS|MODULE_SIG|MODULE_SIG_FORCE|PREEMPT|SMP)=' out/.config || true
VERMAGIC_LINE=$(strings "$BOOT/Image" | grep -m1 -E '^4\.19\.[0-9]+.*SMP' || true)
echo "  Image vermagic: [$VERMAGIC_LINE]"
case "$VERMAGIC_LINE" in
  *modversions*) echo "  OK: vermagic 含 modversions" ;;
  *) echo "FATAL: vermagic 缺少 modversions 标志 (vendor 模块将全部拒载)"; exit 1 ;;
esac
case "$VERMAGIC_LINE" in
  *preempt*) echo "  OK: vermagic 含 preempt" ;;
  *) echo "WARN: vermagic 缺少 preempt 标志" ;;
esac
case "$VERMAGIC_LINE" in
  "4.19.*-perf"*) echo "  OK: 版本串前缀匹配 4.19.x-perf" ;;
  *) echo "WARN: 版本串异常, 原厂为 4.19.157-perf+" ;;
esac

AK3_URL="https://github.com/osm0sis/AnyKernel3"
# 注意: 此时 cwd 仍为 kernel/ (编译目录), ../ 解析有歧义 —— 一律绝对路径。
# 克隆到独立目录 ak3-clone, 绝不覆盖仓库自带模板 ak3/anykernel.sh
# (r31 教训: ../ak3 解析到 $ORIGINAL/ak3, 重试时 rm -rf 把模板删了导致 cp same file)
AK3_DIR="$ORIGINAL/ak3-clone"
rm -rf "$AK3_DIR"
for i in 1 2 3 4 5 6; do
  case $(( (i-1) % 3 )) in
    0) u="$AK3_URL" ;;
    1) u="https://gh-proxy.com/$AK3_URL" ;;
    2) u="https://gitclone.com/github.com/osm0sis/AnyKernel3" ;;
  esac
  echo "  AnyKernel3 尝试 $i: $u"
  if git clone --depth=1 "$u" "$AK3_DIR"; then break; fi
  echo "!! AnyKernel3 clone 失败 (第 $i 次)，重试..."
  rm -rf "$AK3_DIR"
  sleep 10
done
rm -rf "$AK3_DIR/.git"
cp "$ORIGINAL/ak3/anykernel.sh" "$AK3_DIR/anykernel.sh"
cp "$BOOT/Image" "$AK3_DIR/"
mkdir -p "$ORIGINAL/out"
( cd "$AK3_DIR" && zip -r9 "$ORIGINAL/out/AK3-gtneo2-${TAG}-${SUFFIX}.zip" . )

cp "$PWD/out/.config" "$ORIGINAL/out/kernel.config"
cp "$BOOT/Image" "$ORIGINAL/out/Image"
# 记录实际 vermagic 与本机 defconfig 关键项, 便于和原厂 4.19.157-perf+ 逐字比对
{
  echo "== 本构建内核版本/vermagic 期望值 =="
  cat include/config/kernel.release 2>/dev/null || true
  grep -E '^CONFIG_(LOCALVERSION|MODVERSIONS|MODULE_SIG|MODULE_SIG_FORCE|SMP|PREEMPT)=' out/.config || true
} > "$ORIGINAL/out/vermagic-info.txt"
echo "==> 完成! 产物位于 out/:"
ls -lh "$ORIGINAL/out/"
