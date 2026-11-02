# Realme GT Neo 2 (bitra) — SukiSU-Ultra + SusFS 内核编译工程

基于 **realme 官方 Android T（内核 4.19.157）源码**，集成 **SukiSU-Ultra**（kprobe hook）+ **SusFS** 隐藏检测，使用 proton-clang 编译，产出 AnyKernel3 (AK3) 卡刷包。

适配机型：Realme GT Neo 2 / RMX3370（安卓 13 / Realme UI 4.0 底包），同源兼容 X50 Pro 系列（RMX2071/2075/2076/2072）。

## 编译方法（GitHub Actions 云端，免费）

1. 注册/登录 GitHub，新建一个**公开**仓库（公开仓库 Actions 免费不限量）。
2. 把本仓库的全部文件推上去（或直接在网页端上传）：
   ```bash
   git init
   git add .
   git commit -m "GT Neo 2 SukiSU kernel builder"
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```
3. 打开仓库页面 → **Actions** 标签 → 左侧 "Build GT Neo 2 Kernel" → **Run workflow** → 直接点绿色按钮。
4. 等待约 30~60 分钟，进入运行记录页下载 **Artifacts**：
   - `AK3-gtneo2-kona-perf-SukiSU-susfs.zip` ← 推荐先测这个
   - `AK3-gtneo2-kona-SukiSU-susfs.zip` ← perf 版有异常再试这个
   - `Image.gz-dtb`（原始内核镜像）
   - `kernel.config`（内核配置，排查用）

每次想重新编译，改代码或直接再次 Run workflow 即可。

## 刷入步骤（⚠️ 有变砖风险，务必先备份）

**前置条件**：已解锁 BL；手机装有 TWRP / OrangeFox；电脑 adb/fastboot 正常；电量 >50%。

1. **备份原厂 boot（救命稻草，不可跳过）**：
   ```bash
   adb reboot recovery          # 或关机按组合键进 TWRP
   # TWRP 终端或 adb shell 执行:
   dd if=/dev/block/bootdevice/by-name/boot of=/sdcard/boot_backup.img
   adb pull /sdcard/boot_backup.img
   ```
   把 `boot_backup.img` 保存到电脑多个位置。
2. 把 AK3 zip 传到手机（TWRP 的 MTP 或 adb push）。
3. TWRP → Install → 选择 AK3 zip → 刷入 → 重启。
4. 首次开机成功后，安装 **SukiSU-Ultra Manager**（GitHub Releases 下载），授予 root；管理器内置 SusFS 配置页，可配置隐藏路径/挂载来过检测。

## 救砖（卡开机 Logo / 无限重启）

```bash
adb reboot bootloader
fastboot flash boot boot_backup.img
fastboot reboot
```
即恢复原厂内核。所以第 1 步的备份一定要做好。

## 两个 defconfig 怎么选

| defconfig | 说明 |
|---|---|
| `vendor/kona-perf_defconfig` | Oplus 高性能调优配置，真我出厂内核通常基于 perf 版，**首选** |
| `vendor/kona_defconfig` | 标准版。若 perf 版出现相机/WiFi/指纹异常，换这个测试 |

刷完若某功能异常（相机、指纹、充电等），先刷回备份，再换另一个版本测试。

## 已知限制与风险（诚实声明）

- **"零 bug"无法保证**。任何人自编内核都无法承诺。本工程采用社区已验证的配置（ProjectElixir bitra 内核同源、同工具链、同打包方式）将风险降到最低，但真机表现仍以实测为准。
- 官方源码是安卓 13 同代源码（4.19.157），与 RUI 4.0 底包匹配度高，但 Oplus 闭源部分可能存在细微差异。
- 未启用 KPM 内核模块（如需可加 `CONFIG_KPM=y` 及 `CONFIG_KALLSYMS_ALL=y` 重编）。
- SusFS 隐藏需配合 SukiSU-Ultra Manager 使用；过银行/游戏检测还需在管理器内正确配置。
- 刷内核不影响 dtbo/vendor 分区，出问题只需恢复 boot 分区即可，一般不会真砖（可进 fastboot/9008 就能救）。

## 工程结构

```
├── .github/workflows/build-kernel.yml   # Actions 编译流水线（可改 defconfig 列表）
├── build.sh                             # 拉源码 → SukiSU + SusFS → clang 编译 → AK3 打包
└── ak3/anykernel.sh                     # AK3 刷入配置（bitra 分区表）
```

致谢：realme-kernel-opensource（官方源码）、SukiSU-Ultra、susfs4ksu (simonpunk)、kdrag0n（proton-clang）、osm0sis（AnyKernel3）、ProjectElixir-Devices（bitra 参考配置）。

**刷机有风险，操作需谨慎。本工程仅供学习交流。**
