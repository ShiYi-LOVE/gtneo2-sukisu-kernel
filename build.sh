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

KERNEL_URL="https://github.com/realme-kernel-opensource/realme_GTneo2-Q5pro-GTMasterExploratory-AndroidT-kernel-source"
SUSFS_URL="https://gitlab.com/simonpunk/susfs4ksu"

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
  make O=out ARCH=arm64 SUBARCH=arm64 "$DEFCONFIG"
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
}

echo "==> [1/7] 拉取真我官方 Android T 内核源码 (kernel 4.19.157)..."
# 预清理 (绝对路径; 保留仓库自带 ak3/ 模板目录!)
rm -rf kernel out "$ORIGINAL/susfs" "$ORIGINAL/ak3-clone" "$ORIGINAL/bitra-ref"
# 多源回退: 直连 -> 镜像加速 (VM/弱网环境 github 直连常被 reset)
KERNEL_URLS=("$KERNEL_URL"
  "https://gh-proxy.com/$KERNEL_URL"
  "https://ghproxy.net/$KERNEL_URL"
  "https://gitclone.com/github.com/realme-kernel-opensource/realme_GTneo2-Q5pro-GTMasterExploratory-AndroidT-kernel-source")
CLONE_OK=""
for i in 1 2 3 4 5 6; do
  u="${KERNEL_URLS[$(( (i-1) % ${#KERNEL_URLS[@]} ))]}"
  echo "  clone 尝试 $i: $u"
  if git clone --depth=1 "$u" kernel; then CLONE_OK="yes"; break; fi
  rm -rf kernel
  sleep 10
done
[ -n "$CLONE_OK" ] || { echo "FATAL: kernel 源码拉取失败"; exit 1; }
cd kernel

# Oplus Makefile 用 Python2 语法写的 gcc-wrapper.py 包裹编译器，新系统无 python2 会直接报错
# 摘掉包装，保留其内部 REAL_CC 逻辑
sed -i 's|$(PYTHON) $(srctree)/scripts/gcc-wrapper.py ||' Makefile
grep -n "^CC" Makefile | head -3

# OplusKernelEnvConfig.mk 白名单宏会激活引用闭源头文件的核心代码:
#   - SCHED_ASSIST -> mutex.h 闭源调度
#   - VIRTUAL_RESERVE_MEMORY -> linux/reserve_area.h + fs/proc/va_feature_node.h (均未开源)
#   - TASK_CPUSTATS -> account_task_time/fs/proc/task_cpustats (闭源; defconfig 里
#     #ifdef 包 CONFIG 行无效, CONFIG_OPLUS_CTP/SCHED 实际从未开启)
#   - HEALTHINFO -> ion_total()/linux/healthinfo/* (闭源)
#     且官方 defconfig 本就未开启 CONFIG_VIRTUAL_RESERVE_MEMORY, 出厂编译时该特性守卫即为 false
# 从白名单删除宏 = 整个功能编译跳过, 与官方出厂行为一致
sed -i -e '/OPLUS_FEATURE_SCHED_ASSIST/d' -e '/OPLUS_FEATURE_MULTI_FREEAREA/d' \
       -e '/OPLUS_FEATURE_PROCESS_RECLAIM/d' \
       -e '/OPLUS_FEATURE_VIRTUAL_RESERVE_MEMORY/d' \
       -e '/OPLUS_FEATURE_TASK_CPUSTATS/d' \
       -e '/OPLUS_FEATURE_HEALTHINFO/d' OplusKernelEnvConfig.mk
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
echo "OplusKernelEnvConfig.mk: SCHED_ASSIST/MULTI_FREEAREA/PROCESS_RECLAIM/VIRTUAL_RESERVE_MEMORY/TASK_CPUSTATS/HEALTHINFO macros removed; SECURE_GUARD/MOUNT_BLOCK/EXECVE force-exports removed"

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

echo "==> [3d] 自动扫描缺失头文件的 include, 删除对应 OPLUS 白名单宏..."
python3 "$ORIGINAL/fix_oplus_macros.py" || echo "!! 宏清理脚本异常，继续构建"

echo "==> [3d2] 文件级修补 (vmscan/printk 闭源符号缺失 -> 还原 stock 行为)..."
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
echo "  -Werror stripped from $(grep -rl --include='Makefile*' --include='Kbuild*' -e '-Werror' . 2>/dev/null | wc -l) remaining files"

echo "==> [5/7] 配置内核: $DEFCONFIG..."
configure_kernel

echo "==> [6/7] 编译裸 Image (jobs=$JOBS, GNU as —— 4.19 老内核不兼容 LLVM 集成汇编器)..."
BUILD_FLAGS=(O=out ARCH=arm64 SUBARCH=arm64
  CC=clang AR=llvm-ar NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip
  LLVM=1 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_ARM32=arm-linux-gnueabi-
  # Oplus 源码按 GCC 习惯留有 implicit-int/隐式声明等历史问题 (出厂用 GCC 只告警),
  # Clang -Werror 会全部升级为错误 —— 全局降级, 真正的链接错误仍会正常失败
  KCFLAGS="-Wno-error")

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
