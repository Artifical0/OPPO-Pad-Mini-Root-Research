# 16.0.10.500 首次 Root：本机实测路线

实测日期：2026-10-12；整理日期：2026-10-22。机型 `OPD2515 / OP6548L1`，系统 `OPD2515_16.0.10.500(CN01)`，完整内核 `6.12.58-android16-6-g7704a1ae279b-ab15213644-4k`。

最终完成 GBL、真实 BL 解锁和 KernelSU 3.3.0 LKM，之后更新到 3.3.1。首次 KSU 安装及普通重启后的记录见 [ksu-after-normal-reboot.json](../evidence/500/ksu-after-normal-reboot.json)。本页按最终成功记录整理；早期失败没有被删除，也没有被当成稳定提权证明。

## 实际成功路径

```text
备份个人数据、确认精确系统/内核
  → 用对应 boot + xbl_config 编译 preload.so
  → 本机锁屏/息屏状态取得临时 su，核实 UID 0
  → 备份原始分区并核对大小、SHA256
  → 核对旧签名 ABL 与当前固件元数据
  → BDS 写入 efisp，旧签名 ABL 写入本次 b 槽
  → persist/efisp 放置由当前 500 ABL 生成的 Normal EFI 和菜单
  → GBL → Android Tools → BL Tools → Unlock Device
  → Recovery 清数据、重新初始化，Normal Boot 核实真实解锁
  → 用本机原厂 init_boot 修补 KSU LKM
  → 只刷实际活动槽 init_boot，安装管理器并授权 Shell
  → 正常开机及再次普通重启后验证持久 root
```

本机在解锁后进入 Recovery，最终接受格式化。共享存储或 APK 备份不覆盖应用私有数据、聊天、登录态及硬件 Keystore。原始分区备份也不是这些数据的替代品。

## 1. 临时提权材料与失败边界

采用 [koaaN/x9u-preload-builder](https://github.com/koaaN/x9u-preload-builder/tree/18808341a788c2ccb5fb3f071d37d6009c959199)，固定提交 `18808341a788c2ccb5fb3f071d37d6009c959199`；工具链为 NDK r27c `27.2.12479018` 和 GNU Make 4.4.1。

| 输入/产物 | SHA256 |
|---|---|
| 500 boot.img / 原厂 boot_b | `5fd79d25971d171eb18740d37a6fcda56a289bcc4470c642964c988c8b025e72` |
| 完整包提取的 xbl_config.img | `4794f59bc7c82b7d9aab518225c5af797dc51b76a27cf991cc590e4a6a73936b` |
| 生成的 target.h（历史记录） | `43b2dee8b805a7495b971b7787abe5e3e86ff09933a7776fa16a49699191ff58` |
| 本机编译 preload.so，89,840 字节 | `8d7c1957b1485f351238cbb1b55afc5953e5d2285f523a85357966a78ae09fb6` |

发布包中的 `root-work/preload-release/preload.so` 是上述**本机重新编译产物**；这个整理后的目录名不表示它是上游 v1.0.0 的 X9 Ultra 预编译版。旧原帖 SO 与 X9 Ultra release SO 都不应替代本机匹配构建。内核完整字符串相同也不能证明符号、偏移和配置适配。

下载材料后，可在电脑重建（NDK、Make 路径按自己的安装位置填写）：

```powershell
git clone https://github.com/koaaN/x9u-preload-builder.git
git -C x9u-preload-builder checkout 18808341a788c2ccb5fb3f071d37d6009c959199
python x9u-preload-builder/build.py `
  --boot root-work/partitions/locked-20261012_120915/boot_b.img `
  --xbl-config extracted_images/xbl_config.img `
  --ndk-root 'C:/Android/Sdk/ndk/27.2.12479018' `
  --make 'C:/msys64/usr/bin/make.exe'
Get-FileHash x9u-preload-builder/out/preload.so -Algorithm SHA256
```

上游触发入口为将 SO 放入 `/data/local/tmp/preload.so` 后通过 `LD_PRELOAD=/data/local/tmp/preload.so /system/bin/true` 加载；临时客户端是 `/data/local/tmp/su`。本次曾出现以下不同结果：

| 尝试 | 观察 | 能证明什么 |
|---|---|---|
| 旧原包 SO | `slide-kaslr-ok` 后 UBSAN fatal exception / panic | 失败，不能据此进入写入阶段 |
| 本机编译 SO，11:46 左右 | UID 0、su daemon ready，随后 `reboot,malicious_app_try_to_root_devices` | 只证明短暂提权，重启后 su 失效 |
| 本机编译 SO，12:05 锁屏尝试 | direct 阶段 panic | 锁屏不能保证稳定 |
| 本机编译 SO，12:09 后 | 锁屏、屏幕关闭时 su 可用，完成 12 分区备份及备份后三分钟观察 | 本次足够完成后续准备；不是长期稳定性或必现成功率结论 |

锁屏/息屏与后一次可用会话相关，但没有对照实验证明它消除了检测，也没有统计成功率。发生 panic 或检测重启时，当前 su、内核和启动状态都需要重新判断，不能把旧日志里的 UID 0 当作现在仍可写入。

## 2. 原始分区备份与启动链

当时读取了 `boot_a/b`、`init_boot_a/b`、`abl_a/b`、`vbmeta_a/b`、`xbl_config_a/b`、`efisp` 和 `persist`，共 12 个分区、358,637,568 字节。设备端与电脑端大小和 SHA256 一致。persist 在运行时挂载，其副本不是原子快照，含设备专属内容，不公开。

最终启动链是：原厂 XBL → 可加载 GBL 的旧签名 ABL → efisp 中 BDS → persist 中的当前系统 Normal EFI → 原厂 Android + KSU LKM。

| 位置 | 本次实际内容 | 关键摘要 |
|---|---|---|
| `abl_b` | 原帖旧签名 ABL，与固定 GBL 源码的 OPD2515 ABL 一致，完整 1 MiB | `0210487cbc59bdcdb03bb2ee61d9d80fffad8f2ccf35bc7d28d7d9569ad59802` |
| 原始 `efisp` 分区前部 | BDS.efi，290,816 字节；保留其余原始零填充 | BDS `d485e2de52ef7827fd6c5f6b1c56357da422f9a43f86e10b46a945bd17a4e49c` |
| `/mnt/vendor/persist/efisp/ABL_normal.efi` | 从本机 500 原始 ABL 提取并生成 Normal 模式 EFI，774,144 字节 | `6fa5baed02ca05743491afe32e30470f1ec1afb0cca94fe1cd6dbd560242e503` |
| `/mnt/vendor/persist/efisp/BOOTENTRIES` | `Normal Boot:ABL_normal.efi` 与 Android Tools 入口 | 见材料清单 |

关键区别：**旧签名 ABL 分区镜像用于 GBL 入口；当前版本的 Normal EFI 用于启动当前系统。** 原包随附的旧 Normal / Fake Locked EFI 没有直接作为本机 500 Normal 使用。`efisp` 块分区和 persist 里的同名目录是不同位置；EFI 应用也不是完整 ABL 分区镜像。

部署前验证了 MBNv7 签名、证书链、分段 SHA384、共同/OEM 元数据；相关镜像 ARB 字段为 0。没有读取 eFuse，不据此保证随意降级。写后回读两处块分区与文件摘要，并确认 a 槽 ABL、b 槽 boot/init_boot 未被这一步修改。见 [gbl-deployment.json](../evidence/500/gbl-deployment.json)。该记录停在解锁流程中间，后面的 KSU 重启记录才是最终成功证据。

## 3. GBL、解锁和 Windows 驱动

按住音量上键配合重启进入 GBL，先用 Normal Boot 确认 500 可启动。此时仍为 locked/green，临时 su 已失效；出现 GBL 菜单不等于已经解锁。

随后在 `Android Tools → BL Tools` 检查当前状态，再执行 `Unlock Device`。本次最终进入 Recovery 并格式化，重新初始化和授权 USB 调试后，回到 Normal Boot 读取真实状态与活动槽。没有执行 Unlock Critical、Lock Device 或 ARB 修改。

本次 Superfastboot 的 USB 硬件 ID 为 `VID_18D1&PID_D00D`；Windows Code 28 通过对明确选中的设备实例绑定原始 Google 签名 Android Bootloader Interface 驱动解决，没有修改 INF 或关闭签名检查。复用工具见 `tools/Bind-Fastboot-Driver.ps1`，需要明确提供自己的设备实例和签名 INF 路径，默认仅检查。

该 Superfastboot 未实现 `getvar unlocked/current-slot/is-userspace/max-fetch-size` 等查询。查询失败不表示未解锁；当时通过回到 Android 的真实 Normal Boot 检查及分区读取确定状态。系统属性隐藏开启后，还应结合原始 `/proc/bootconfig` 中 `vbmeta.device_state` 与 `verifiedbootstate`，不能用隐藏后的 locked/green 证明已回锁。

## 4. KSU 持久 root

实际首次安装使用官方 KSU **3.3.0**，`android16-6.12`、aarch64 LKM，修补本机原厂 `init_boot_b`。管理器、ksud、ksuinit、LKM 应保持同一版本。离线命令如下，输出目录须新建且为空：

```powershell
New-Item -ItemType Directory -Path ./ksu-500-output
& ./root-work/tools/ksud-x86_64-pc-windows-gnu.exe boot-patch `
  --boot ./root-work/partitions/locked-20261012_120915/init_boot_b.img `
  --module ./root-work/tools/lkm-aarch64-android16-6.12_kernelsu.ko `
  --init ./root-work/tools/ksuinit-aarch64 `
  --kmi android16-6.12 --arch aarch64 `
  --out ./ksu-500-output --out-name kernelsu_patched-init_boot.img
```

这里的 `--boot` 是输入参数名，传入的是 init_boot；没有更换原厂 boot 内核。实测修补输入为 8 MiB，SHA256 `4a7e06fa940b83657b26f5d4a8a3a3f83cec3f906d0c416e85282ca4993d4b9f`；本次产物同为 8 MiB，SHA256 `d30bb67358aee1a5ef3b2ba88aeb68220d14f8e68c67e9a0cb5019fce845b75a`。重新构建应重新登记摘要，不用旧值替代本次检查。

本次确认真实解锁、活动槽仍 b、容量 `0x800000` 后，实际只写入 `init_boot_b`，回读摘要一致。b 是本机当次的实际槽位，不是给所有设备的固定刷写目标。安装同版管理器并授权 Shell 后，再正常重启一次，不重新运行 preload。

重启后的结果是 500/b、原厂内核不变、UID 0、`ksud 3.3.0 (uapi: 2)`、KSU LKM Live、SELinux Enforcing，修补后的 init_boot 摘要匹配，boot 未改变。后续 500 上更新到 KSU 3.3.1/uapi 5，才开始 103 升级研究。

## 5. 验证与恢复范围

已验证：本机 GBL 菜单、500 Normal Boot、真实解锁、KSU 持久 root 与普通重启。没有验证 EDL/9008 救砖、任意版本降级或重新回锁。失败时必须区分临时 su 丢失、GBL 入口损坏、Normal EFI 不匹配、init_boot 修补失败与模块异常。

保留原始 ABL / efisp / init_boot 是恢复准备，不保证恢复通道一定能写回。已改 ABL 时只恢复 efisp 不等于完整撤销。仍有修补镜像时直接回锁可能使设备无法启动。

来源：[原酷安记录](https://www.coolapk.com/feed/73496160)、[固定 GBL 源码](https://github.com/ditvelo/gbl_root_canoe/tree/2cf345a299df3f8b7172d6ad2fa5985e67fe53d6)、[KernelSU v3.3.0](https://github.com/tiann/KernelSU/releases/tag/v3.3.0)、[KernelSU 安装说明](https://kernelsu.org/guide/installation.html)。原帖二进制缺少可对应的构建提交；本仓库不声称已证明其与固定源码逐字节对应。
