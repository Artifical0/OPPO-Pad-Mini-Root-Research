# 从 500 升级 ColorOS 17.0.0.103，并保留 GBL / KSU

[返回首页](../README.md) · 首次解锁请先看 [500 Root 指南](500-root.md) · 后续版本看 [OTA 助手](../ota-helper/README.md)

本机已完成这条升级路线：首次进入 103、更新快照合并、再次普通重启，以及恢复原 5 个模块后的重启均通过。实测日期为 2026-10-14。

## 适用条件

| 项目 | 升级前 | 升级后 |
|---|---|---|
| 型号 | OPD2515 / OP6548L1 | 同一台设备 |
| 系统 | 16.0.10.500(CN01) | 17.0.0.103(CN01) |
| 内核 | 6.12.58-android16-6 | 6.12.69-android16-6 |
| KSU | 3.3.1 / uapi 5，LKM | 3.3.1 / uapi 5，LKM Live |
| 实际槽位 | b | a |
| BL | 真实 unlocked / orange | 保持真实解锁 |

需要已有可用 GBL、持久 KSU root 和真实解锁。**b → a 只代表本次实测；其他设备读取自己的当前槽与目标槽。**

## 1. 准备数据、工具与固件

1. 备份照片、文件、聊天和应用数据，确认 GBL / USB 恢复入口能用。
2. 停用第三方模块并重启，先处理完排队的模块更新；系统 OTA、快照合并均处于空闲状态。
3. 按[首页](../README.md#获取工具和材料)下载并校验研究材料，自行取得 [103 官方完整包](firmware.md)。
4. 备份当前启动镜像、现用 EFI 与菜单；保留足够电量、空间和稳定 USB 连接，关闭系统提供的自动安装、自动重启选项。

可在平板 root shell 中检查当前状态：

```sh
getprop ro.product.model
getprop ro.build.display.id
getprop ro.boot.slot_suffix
uname -r
id
/data/adb/ksud -V
```

真实解锁状态结合原始 `/proc/bootconfig` 判断。隐藏模块修改过的 locked / green 属性不代表真实回锁。

## 2. 准备 103 对应的两个新文件

| 文件 | 来源与作用 |
|---|---|
| 103 KSU init_boot | 103 原厂 init_boot 经 KSU 3.3.1 修补，提供新版系统的 root |
| 103 Normal EFI | 从 103 原厂 ABL 提取并按 Normal 模式修补，启动新版系统 |
| 保留的旧签名 ABL | 继续提供 GBL 入口，使用已核对的完整 1 MiB 镜像 |

这些文件已收录在材料包，完整路径见[工具索引](tools.md)。自行重新生成时，检查工具输出、镜像格式、长度和摘要；Normal EFI 使用 `normal` 模式。

103 是 Android 17，但本次内核 KMI 仍为 **`6.12-android16-6`**，因此 KSU LKM 选择 **`android16-6.12` / aarch64**。不能只按 Android 大版本选 LKM。

本次启动链为：

```text
官方 XBL → 旧签名 ABL → GBL/BDS → 103 Normal EFI → Android 17 + 103 KSU init_boot
```

升级前需单独审查旧 ABL 与目标 XBL、xbl_config、TZ 等固件的签名、认证元数据及防回滚条件。本次没有读取硬件熔丝；已验证组合不能推导为任意版本可用。

## 3. 官方本地安装，停在重启前

在系统更新的本地安装中选择已校验的 103 完整包，安装完成后保持当前系统运行。

核对实际目标槽启动镜像与完整包一致，并确认 Boot HAL 的下次启动槽、可启动标记、快照状态和 UpdateEngine 的 `UPDATED_NEED_REBOOT (6)`。本次对 47 项目标镜像范围及安装元数据进行了核对。

**103 采用过延期激活流程：出现“立即重启”时，目标槽可能尚未激活。** 必须先校验安装完成记录、已认证 payload 元数据、原生适用性及目标镜像，再由系统 UpdateEngine 完成激活。这属于这次专门适配的流程，相关源码为 `precheck_deferred_17.py` 与 `activate_deferred_17.py`，见[设备工具说明](tools.md#设备侧工具)。

新 OTA 助手不会自动执行延期激活，也不能替代本次 500 → 103 的专用检查。

## 4. 备份并保留目标槽

写入前备份目标槽刚安装的 init_boot、完整 ABL，以及当前 Normal EFI、菜单和源槽启动文件。核对长度与 SHA256，并在电脑保留一份。

| 位置 | 本次处理 |
|---|---|
| 目标槽 init_boot | 写入 103 KSU 修补镜像 |
| 目标槽 abl | 写回已审查的旧签名 ABL |
| persist 中的 `ABL_normal.efi` | 更新为 103 Normal EFI |
| persist 中的 `ABL_500.efi` / `ABL_17.efi` | 分别保存旧、新 EFI 材料 |
| `BOOTENTRIES` | 默认指向新版 Normal EFI，保留命名的备用入口 |

写入后同步并逐项回读摘要，再确认源槽启动分区、原始 BDS 与待启动状态符合计划。共享 persist 不随槽位自动回退，需要单独保存和核对。

此操作不重新刷 BDS，不锁 BL、不修改 ARB、不清数据。底层固件由官方 OTA 安装。本次 `guarded_17.py` 事务工具保留了版本、槽位和镜像摘要检查，不能通过改后缀直接套用到别的设备。

## 5. 开机与验证

1. 写入与读回全部通过后，按住音量上键配合正常重启，确认 GBL 菜单出现。
2. 选择指向 103 EFI 的 **Normal Boot**，等待系统首次启动并解锁屏幕。
3. 核对系统版本、实际槽位、内核、KSU、Shell root 和个人数据。
4. 等待快照合并结束，由 `MERGING` 变为 `NONE`，再普通重启一次。
5. 确认默认启动进入 103、root 保持正常后，再恢复第三方模块并分别验证。

本机最终状态：

```text
系统：OPD2515_17.0.0.103(CN01)，Android 17 / SDK 37
内核：6.12.69-android16-6-g242e1a07f878-ab15865446-4k
KSU：ksud 3.3.1 (uapi: 5)，LKM Live
Shell：UID 0；SELinux：Enforcing
快照：合并完成；普通重启：通过
```

记录：[首次开机](../evidence/17-103/first-boot.json)、[再次重启](../evidence/17-103/second-boot.json)、[恢复模块后重启](../evidence/17-103/modules-enabled-boot.json)。

## 本次材料摘要

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| 103 完整 ZIP | 9,214,591,270 | `aeeb3029c64f3a7251bf861325a21388c1817739c8684155ba7daa71f6beb8d5` |
| 103 原厂 init_boot | 8,388,608 | `202332d30498b52967da93e1272a871161ec04e4e5825c7b541cddcce9a64516` |
| 本次 KSU init_boot | 8,388,608 | `ddd0e19a562a33040f99282e23db848b4371d66b88581952843be33bfd516fc3` |
| 旧签名 ABL | 1,048,576 | `0210487cbc59bdcdb03bb2ee61d9d80fffad8f2ccf35bc7d28d7d9569ad59802` |
| 103 Normal EFI | 782,336 | `2efe7efced64c4caaea203277245e16ff0523e800a82ff87cc44642f8b3f4170` |

以后更新需要重新准备目标版本的 EFI / KSU 并审查启动链，见 [OTA 助手说明](../ota-helper/README.md)。本次已验证路线没有使用旧 OTA Helper RC2。完整 OTA 与增量 OTA 的源分区校验要求不同，现有记录不保证管理器“恢复原厂镜像”或以后增量包可用。

参考：[KernelSU 3.3.1](https://github.com/tiann/KernelSU/releases/tag/v3.3.1)、[GBL OTA 说明](https://github.com/SuperTurtleDev/gbl_root_canoe/blob/8cc6fa5ad467af6d34a00f401290035ee87a14c7/wiki/docs/zh/ota.md)。
