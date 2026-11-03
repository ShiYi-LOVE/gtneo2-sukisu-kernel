### AnyKernel3 Ramdisk Mod Script
## osm0sis @ xda-developers
## Realme GT Neo 2 (bitra) — SukiSU-Ultra + SusFS
## 注意: AK3 v2+ 的 shell 变量必须大写 (BLOCK/IS_SLOT_DEVICE/...),
##   小写 block= 不会被 ak3-core.sh 识别 -> "Unable to determine  partition"
##   (r32 首刷实测踩坑; auto = 自动探测分区路径与 slot, 抗 recovery 差异)

# begin properties
properties() { '
kernel.string=Realme GT Neo 2 (bitra) | SukiSU-Ultra + SusFS
do.devicecheck=0
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
device.name1=RMX3370
device.name2=RMX2071
device.name3=RMX2076
device.name4=RMX2075
device.name5=RMX2072
supported.versions=
supported.patchlevels=
'; } # end properties

# shell variables (UPPERCASE, AK3 v2+ convention)
BLOCK=auto;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

## AnyKernel methods (DO NOT CHANGE)
. tools/ak3-core.sh;

## AnyKernel boot install
dump_boot;

vbmeta_disable_verification;

write_boot;
## end boot install
