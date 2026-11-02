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
git clone --depth=1 "$KERNEL_URL" kernel
cd kernel

# Oplus Makefile 用 Python2 语法写的 gcc-wrapper.py 包裹编译器，新系统无 python2 会直接报错
# 摘掉包装，保留其内部 REAL_CC 逻辑
sed -i 's|$(PYTHON) $(srctree)/scripts/gcc-wrapper.py ||' Makefile
grep -n "^CC" Makefile | head -3

echo "==> [2/7] 集成 SukiSU-Ultra (main 分支, kprobe hook)..."
curl -LSs "https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/main/kernel/setup.sh" | bash -s main

echo "==> [3/7] 应用 SusFS 补丁 (kernel-4.19 分支)..."
git clone --depth=1 -b kernel-4.19 "$SUSFS_URL" ../susfs
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

echo "==> [4/7] 拉取 Neutron Clang 工具链 (proton-clang 过老，ld 无法链接新 glibc)..."
mkdir -p "$PWD/neutron-clang" && cd "$PWD/neutron-clang"
curl -LOs "https://raw.githubusercontent.com/Neutron-Toolchains/antman/main/antman"
chmod +x antman
./antman -S=latest
cd - > /dev/null
export PATH="$PWD/neutron-clang/bin:$PATH"
clang --version | head -1

echo "==> [5/7] 配置内核: $DEFCONFIG..."
configure_kernel

echo "==> [6/7] 编译 Image.gz + dtbs (jobs=$JOBS)..."
BUILD_FLAGS=(O=out ARCH=arm64 SUBARCH=arm64
  CC=clang AR=llvm-ar NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip
  LLVM=1 CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_ARM32=arm-linux-gnueabi-)

if ! make "${BUILD_FLAGS[@]}" LLVM_IAS=1 -j"$JOBS" Image.gz dtbs; then
  echo "!! LLVM_IAS=1 编译失败，回退 GNU as 重新编译..."
  rm -rf out
  configure_kernel
  make "${BUILD_FLAGS[@]}" -j"$JOBS" Image.gz dtbs
fi

echo "==> [7/7] 打包 Image.gz-dtb 与 AnyKernel3 卡刷包..."
BOOT="$PWD/out/arch/arm64/boot"
find "$BOOT/dts" -name '*.dtb' -type f | sort | xargs cat > "$BOOT/dtb.concat"
cat "$BOOT/Image.gz" "$BOOT/dtb.concat" > "$BOOT/Image.gz-dtb"

git clone --depth=1 https://github.com/osm0sis/AnyKernel3 ../ak3
rm -rf ../ak3/.git
cp "$ORIGINAL/ak3/anykernel.sh" ../ak3/anykernel.sh
cp "$BOOT/Image.gz-dtb" ../ak3/
( cd ../ak3 && zip -r9 "$ORIGINAL/out/AK3-gtneo2-${TAG}-SukiSU-susfs.zip" . )

cp "$PWD/out/.config" "$ORIGINAL/out/kernel.config"
echo "==> 完成! 产物位于 out/:"
ls -lh "$ORIGINAL/out/"
