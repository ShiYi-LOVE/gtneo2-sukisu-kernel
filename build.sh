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

KERNEL_URL="https://github.com/realme-kernel-opensource/realme_GTneo2-Q5pro-GTMasterExploratory-AndroidT-kernel-source"
SUSFS_URL="https://gitlab.com/simonpunk/susfs4ksu"

export KBUILD_BUILD_USER="SukiSU"
export KBUILD_BUILD_HOST="gtneo2"
export KBUILD_BUILD_TIMESTAMP="Thu Jan 1 00:00:00 UTC 2026"

mkdir -p "$ORIGINAL/out"

KSU_CONFIG_OPTS=(
  KSU
  KSU_SUSFS
  KSU_SUSFS_SUS_PATH
  KSU_SUSFS_SUS_MOUNT
  KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
  KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
  KSU_SUSFS_ENABLE_LOG
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
  make O=out ARCH=arm64 olddefconfig
}

echo "==> [1/7] 拉取真我官方 Android T 内核源码 (kernel 4.19.157)..."
rm -rf kernel ../susfs ../ak3 out
for i in 1 2 3 4 5; do
  git clone --depth=1 "$KERNEL_URL" kernel && break
  echo "!! kernel clone 失败 (第 $i 次)，重试..."
  rm -rf kernel
  sleep 10
done
[ -d kernel ] || { echo "FATAL: kernel 源码拉取失败"; exit 1; }
cd kernel

# Oplus Makefile 用 Python2 语法写的 gcc-wrapper.py 包裹编译器，新系统无 python2 会直接报错
# 摘掉包装，保留其内部 REAL_CC 逻辑
sed -i 's|$(PYTHON) $(srctree)/scripts/gcc-wrapper.py ||' Makefile
grep -n "^CC" Makefile | head -3

# OplusKernelEnvConfig.mk 白名单宏 OPLUS_FEATURE_SCHED_ASSIST 会激活 mutex.h 等核心头文件
# 对闭源 vendor 头文件的 include (头文件从未开源) —— 从白名单删除, 整个功能编译跳过
# (与社区 bitra 内核做法一致: sched_assist 闭源调度整体禁用)
sed -i -e '/OPLUS_FEATURE_SCHED_ASSIST/d' -e '/OPLUS_FEATURE_MULTI_FREEAREA/d' OplusKernelEnvConfig.mk
echo "OplusKernelEnvConfig.mk: SCHED_ASSIST / MULTI_FREEAREA macros removed"

echo "==> [2/7] 集成 SukiSU-Ultra (main 分支, kprobe hook)..."
for i in 1 2 3 4 5; do
  curl -LSs --retry 5 --retry-delay 5 --retry-all-errors \
    "https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/main/kernel/setup.sh" | bash -s main && break
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

echo "==> [3b] Kconfig 占位修复 (Oplus 发布源码缺失的 Kconfig 文件)..."
python3 "$ORIGINAL/kconfig_stubs.py" || echo "!! 占位脚本异常，继续构建"

echo "==> [3c] 应用 susfs realme 适配补丁 (官方 hunk 不兼容 Oplus 源码的 5 处)..."
python3 "$ORIGINAL/fix_susfs.py" || echo "!! susfs 适配脚本异常，继续构建"

echo "==> [3c2] 从社区 bitra 内核回填 Oplus 闭源组件 (system/device_info/sensor/thermal)..."
# realme 官方源码 drivers/soc/oplus/{system,device_info,sensor,thermal} 和 include/soc/oplus
# 全部指向未开源 vendor 目录 (失效符号链接)。ProjectElixir bitra 内核 (同设备, 已验证可编译)
# 补全了这些组件 —— 直接回填, 让 oplus_project.h 等头文件及其实现恢复存在
for i in 1 2 3 4 5; do
  git clone --depth=1 -b bigshot-AOSP https://github.com/ProjectElixir-Devices/kernel_realme_sm8250-bitra ../bitra-ref && break
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
  [ -f include/soc/oplus/system/oplus_project.h ] || echo "!! 警告: oplus_project.h 回填失败, 后续编译可能报缺失"
else
  echo "!! bitra-ref 不可用，缺失组件按空 stub 处理"
fi

echo "==> [3d] 自动扫描缺失头文件的 include, 删除对应 OPLUS 白名单宏..."
python3 "$ORIGINAL/fix_oplus_macros.py" || echo "!! 宏清理脚本异常，继续构建"

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

echo "==> [5/7] 配置内核: $DEFCONFIG..."
configure_kernel

echo "==> [6/7] 编译 Image.gz + dtbs (jobs=$JOBS, GNU as —— 4.19 老内核不兼容 LLVM 集成汇编器)..."
BUILD_FLAGS=(O=out ARCH=arm64 SUBARCH=arm64
  CC=clang AR=llvm-ar NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip
  LLVM=1 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_ARM32=arm-linux-gnueabi-)

if ! make "${BUILD_FLAGS[@]}" -j"$JOBS" Image.gz dtbs; then
  echo "!! 编译失败，清理后重试一次..."
  rm -rf out
  configure_kernel
  make "${BUILD_FLAGS[@]}" -j"$JOBS" Image.gz dtbs
fi

echo "==> [7/7] 打包 Image.gz-dtb 与 AnyKernel3 卡刷包..."
BOOT="$PWD/out/arch/arm64/boot"
find "$BOOT/dts" -name '*.dtb' -type f | sort | xargs cat > "$BOOT/dtb.concat"
cat "$BOOT/Image.gz" "$BOOT/dtb.concat" > "$BOOT/Image.gz-dtb"

for i in 1 2 3 4 5; do
  git clone --depth=1 https://github.com/osm0sis/AnyKernel3 ../ak3 && break
  echo "!! AnyKernel3 clone 失败 (第 $i 次)，重试..."
  rm -rf ../ak3
  sleep 10
done
rm -rf ../ak3/.git
cp "$ORIGINAL/ak3/anykernel.sh" ../ak3/anykernel.sh
cp "$BOOT/Image.gz-dtb" ../ak3/
( cd ../ak3 && zip -r9 "$ORIGINAL/out/AK3-gtneo2-${TAG}-SukiSU-susfs.zip" . )

cp "$PWD/out/.config" "$ORIGINAL/out/kernel.config"
echo "==> 完成! 产物位于 out/:"
ls -lh "$ORIGINAL/out/"
