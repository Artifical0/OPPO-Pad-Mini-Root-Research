# 500 首次 Root 指南

[返回首页](../README.md) · 下一步：[升级 ColorOS 17.0.0.103](17-103-upgrade.md)

这条路线在同一台 OPPO Pad Mini 上完成了 **临时提权 → GBL → 真实 BL 解锁 → KernelSU LKM 持久 root**，普通重启后仍有 root。实测日期为 2026-10-12。

## 开始前确认

| 项目 | 本指南对应值 |
|---|---|
| 型号 | OPD2515 / OP6548L1 |
| 系统 | `OPD2515_16.0.10.500(CN01)` |
| 内核 | `6.12.58-android16-6-g7704a1ae279b-ab15213644-4k` |
| KSU | 首次安装 3.3.0 / uapi 2，后续更新至 3.3.1 / uapi 5 |
| 内核模块 | aarch64，`android16-6.12` |

**先备份个人数据。首次解锁进入 Recovery 并清除数据。** 启动分区备份不包含聊天记录、应用私有数据或登录态。本指南只覆盖上述固件组合。

按[首页](../README.md#获取工具和材料)下载材料并完成校验。准备 ADB、Fastboot 和可用 USB 连接。下文电脑命令均从仓库根目录运行。

## 1. 获取本次匹配的临时 root

材料中的 `root-work/preload-release/preload.so` 是使用本机 500 的 boot 和 xbl_config 重新编译的产物，SHA256：

```text
8d7c1957b1485f351238cbb1b55afc5953e5d2285f523a85357966a78ae09fb6
```

先通过 `adb devices` 确认只连接目标设备，再复制 SO：

```powershell
adb push root-work/preload-release/preload.so /data/local/tmp/preload.so
adb shell
```

在平板 shell 中加载，随后检查临时客户端：

```sh
LD_PRELOAD=/data/local/tmp/preload.so /system/bin/true
/data/local/tmp/su -c id
```

本机可用会话是在锁屏、息屏状态取得的。只有本次客户端确实返回 UID 0，才能继续读取备份；临时 root 没有被当成稳定驻留方案。该入口可能导致系统重启，应在完成个人数据备份后研究。

需要自行编译时，使用 [x9u-preload-builder 固定提交](https://github.com/koaaN/x9u-preload-builder/tree/18808341a788c2ccb5fb3f071d37d6009c959199)、NDK r27c 与 GNU Make：

```powershell
python x9u-preload-builder/build.py `
  --boot root-work/partitions/locked-20261012_120915/boot_b.img `
  --xbl-config extracted_images/xbl_config.img `
  --ndk-root 'C:/Android/Sdk/ndk/27.2.12479018' `
  --make 'C:/msys64/usr/bin/make.exe'
```

工具链路径按实际安装位置填写。自行构建产物应另行核对摘要。

## 2. 备份启动文件，准备 GBL

读取自己的实际槽位，备份两槽的 `boot`、`init_boot`、`abl`、`vbmeta`、`xbl_config`，以及原始 `efisp` 和 `persist`。本机当时共备份 12 个分区；每份备份都核对设备端和电脑端的长度与 SHA256。使用二进制安全的导出方式，避免用 PowerShell 文本重定向保存镜像。

启动链的部署关系如下：

| 部署位置 | 使用的材料 | 用途 |
|---|---|---|
| 实际启动槽的 `abl` | 旧签名 ABL，完整 1 MiB | 进入 GBL |
| 原始 `efisp` 分区前部 | `BDS.efi`，290,816 字节 | GBL 菜单；保留分区剩余原始内容 |
| `/mnt/vendor/persist/efisp/ABL_normal.efi` | **500 对应** Normal EFI，774,144 字节 | 启动 500 |
| 同一目录的 `BOOTENTRIES` | 默认 Normal Boot 与 Android Tools 入口 | 选择启动项 |
| 同一目录的 `tools/` | BLTools、RebootTools 与 ENTRIES | 解锁和启动工具 |

文件的完整电脑路径见[工具索引](tools.md)。部署前核对旧 ABL 与当前固件的签名、证书链、分段摘要及认证元数据，写入后逐项回读；本机部署记录在 [gbl-deployment.json](../evidence/500/gbl-deployment.json)。原始 `efisp` 分区和 persist 里的同名目录是两个位置，Normal EFI 也不是完整 ABL 分区镜像。

这里保留设备相关的写入边界，没有提供硬编码槽位的一键部署命令。**本机当时使用 b 槽，其他设备应独立确认。**

## 3. 在 GBL 中完成真实解锁

1. 按住音量上键配合重启进入 GBL，先用 **Normal Boot** 确认 500 能启动。
2. 再进入 `Android Tools → BL Tools`，核对状态，执行 **Unlock Device**。
3. 完成 Recovery 的数据清除和系统初始化，重新开启 USB 调试。
4. 返回 Normal Boot，检查实际槽位和 `/proc/bootconfig` 中的真实解锁状态：`vbmeta.device_state = "unlocked"`、`verifiedbootstate = "orange"`。

本次没有使用 Unlock Critical、Lock Device 或 ARB 修改。Windows 如需绑定 Bootloader 驱动，使用 Google 原始签名驱动；[驱动工具说明](tools.md#设备侧工具)提供限定设备实例的辅助脚本。

## 4. 安装持久 KernelSU root

使用同一版本的管理器、ksud、ksuinit 和 LKM。本机首次使用 3.3.0，修补 500 原厂 **init_boot**，没有替换 boot 内核：

```powershell
New-Item -ItemType Directory -Path ./ksu-500-output
& ./root-work/tools/ksud-x86_64-pc-windows-gnu.exe boot-patch `
  --boot ./root-work/partitions/locked-20261012_120915/init_boot_b.img `
  --module ./root-work/tools/lkm-aarch64-android16-6.12_kernelsu.ko `
  --init ./root-work/tools/ksuinit-aarch64 `
  --kmi android16-6.12 --arch aarch64 `
  --out ./ksu-500-output --out-name kernelsu_patched-init_boot.img
```

`--boot` 是输入参数名，这里传入的是 init_boot。确认真实解锁、实际槽位和分区容量后，只将修补镜像写入**已确认的活动槽 init_boot**，回读摘要一致后启动系统。安装同版 KSU 管理器并授权 Shell，再普通重启一次，不重新运行 preload。

## 5. 确认完成

进入 `adb shell`，执行 `su` 后检查：

```sh
id
getprop ro.build.display.id
getprop ro.boot.slot_suffix
uname -r
/data/adb/ksud -V
grep '^kernelsu ' /proc/modules
getenforce
```

应为 500、UID 0、正确 KSU 版本、LKM Live、SELinux Enforcing，普通重启后保持一致。实际结果见 [重启验证记录](../evidence/500/ksu-after-normal-reboot.json)。

关键材料 SHA256：

| 文件 | SHA256 |
|---|---|
| 旧签名 ABL | `0210487cbc59bdcdb03bb2ee61d9d80fffad8f2ccf35bc7d28d7d9569ad59802` |
| BDS | `d485e2de52ef7827fd6c5f6b1c56357da422f9a43f86e10b46a945bd17a4e49c` |
| 500 Normal EFI | `6fa5baed02ca05743491afe32e30470f1ec1afb0cca94fe1cd6dbd560242e503` |

保留自己的原始分区与 EFI 备份。现有验证不包含 EDL/9008 恢复或重新回锁。

来源：[原始讨论](https://www.coolapk.com/feed/73496160)、[固定 GBL 源码](https://github.com/ditvelo/gbl_root_canoe/tree/2cf345a299df3f8b7172d6ad2fa5985e67fe53d6)、[KernelSU 安装说明](https://kernelsu.org/guide/installation.html)。
