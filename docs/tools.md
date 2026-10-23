# 工具与材料索引

[返回首页](../README.md) · [500 Root](500-root.md) · [500 → 103](17-103-upgrade.md) · [后续 OTA 助手](../ota-helper/README.md)

先在仓库根目录运行下面三条命令。所有材料保留原来的目录结构，方便按表查找：

```powershell
python -m pip install -r requirements.txt
python tools/fetch_materials.py
python tools/verify_materials.py .
```

下载与校验仅操作电脑文件。全部 38 个材料的大小、SHA256 和来源见 [materials-manifest.json](../materials-manifest.json)。完整 ROM 另见[固件指纹](firmware.md)。

## 按用途找文件

| 用途 | 材料 | 仓库根目录下的完整路径 |
|---|---|---|
| 500 临时 root | 本机编译的 preload | `root-work/preload-release/preload.so` |
| GBL 入口 | 旧签名完整 ABL | `root-work/coolapk-original/oppo_pad_mini_root_file/abl_a.img` |
| GBL 菜单 | BDS | `root-work/gbl/deploy-original-20261012_144259/payload/BDS.efi` |
| GBL 工具 | BLTools / RebootTools / ENTRIES | `root-work/gbl/deploy-original-20261012_144259/payload/efisp/tools/` |
| 500 系统启动 | 500 Normal EFI | `root-work/gbl/compatibility-20261012_122445/current_b/ABL_normal.efi` |
| 500 首次 KSU | 3.3.0 的 ksud、ksuinit、LKM、管理器 | `root-work/tools/` |
| 500 KSU 修补输入 | 原厂 init_boot | `root-work/partitions/locked-20261012_120915/init_boot_b.img` |
| 500 已验证 KSU | 3.3.0 修补镜像 | `root-work/patched/KernelSU-v3.3.0-slot-b-20261012_145008/kernelsu_patched-init_boot.img` |
| 103 系统启动 | 103 Normal EFI | `root-work/ColorOS17-17.0.0.103-analysis/candidates-offline/ABL_normal-17.efi` |
| 103 KSU 修补输入 | 原厂 init_boot | `root-work/ColorOS17-17.0.0.103-analysis/images-17/init_boot.img` |
| 103 已验证 KSU | 3.3.1 修补镜像 | `root-work/ColorOS17-17.0.0.103-analysis/candidates-offline/KSU-3.3.1-init_boot-17.img` |
| KSU 3.3.1 | ksud、ksuinit、LKM、管理器 | `root-work/ColorOS17-17.0.0.103-analysis/ksu-3.3.1-tools/` |
| 提取 EFI | extractfv.exe | `root-work/gbl-source/submodules/ablfvextractor/build/extractfv.exe` |
| 生成 Normal EFI | patch_abl.exe | `root-work/gbl-source/submodules/patcher/build/patch_abl.exe` |
| 研究源码 | GBL / KernelSU / preload 固定源码快照 | `sources/` |
| 后续 OTA | 0.2.0-rc1 模块源码、构建和保留包生成器 | `ota-helper/` |

旧 ABL 用于完整 abl 分区，Normal EFI 用于 persist 中的文件；两者不能混用。文件名中的 a / b 是历史采集时的槽位，不指定读者的刷写目标。随 GBL 工具附带的 ArbTools 不在本指南使用步骤中。

## 电脑端离线工具

| 操作 | 命令入口 | 设备访问 |
|---|---|---|
| 下载固定材料 | `python tools/fetch_materials.py` | 无 |
| 校验 38 个文件 | `python tools/verify_materials.py .` | 无 |
| 查看 payload 分区和操作类型 | `python OPD2515-OTA-Helper/tools/inspect_payload.py --help` | 无 |
| 比较两个 payload | `python OPD2515-OTA-Helper/tools/compare_payloads.py --help` | 无 |
| 提取指定原厂镜像并校验 | `python OPD2515-OTA-Helper/tools/extract_selected_payload.py --help` | 无 |
| 校验 OTA 整包签名与 CRC | `python OPD2515-OTA-Helper/tools/verify_ota_zip.py --help` | 无 |
| 构建新 OTA 模块 | `python ota-helper/build.py` | 无 |
| 审查并生成每次 OTA 保留包 | `python ota-helper/prepare_update.py --help` | 无 |

新保留包生成器使用上述经过测试的解析器，同时核验整包签名、完整固件清单和本次备份。具体命令见 [OTA 助手说明](../ota-helper/README.md)。历史 `review.py` / `Review-OTA.ps1` 面向旧 RC2，研究新版本使用 `ota-helper/prepare_update.py`。

## 设备侧工具

| 工具 | 作用与写入范围 |
|---|---|
| `guarded_17.py check` | 读取设备，验证本次专用 500 → 103 计划 |
| `guarded_17.py apply` | 写目标 init_boot、ABL 和共享 EFI / 菜单；固定历史版本、槽位和摘要 |
| `precheck_deferred_17.py` | 读取并审查 103 本地安装与延期激活条件 |
| `activate_deferred_17.py` | 经专用检查后调用 UpdateEngine 激活目标槽，并暂停更新 UI |
| 新模块的 status / export / import / preview | 检查设备、导出启动备份、导入保留包或预览；不写启动分区 |
| 新模块的 apply | 有确认短语才备份并写目标 init_boot、ABL 与 Normal EFI，随后回读 |

专用 Python 设备工具在 `OPD2515-OTA-Helper/tools/`。使用前明确自己的设备选择：

```powershell
$env:OPD_ADB = 'C:/Android/Sdk/platform-tools/adb.exe'
$env:OPD_SERIAL = '填写 adb devices 显示的目标序列号'
python OPD2515-OTA-Helper/tools/guarded_17.py --help
```

设备选择不改变工具内部的版本与槽位检查。历史 b → a 计划不能直接作为他人的通用计划。

Windows D00D Bootloader 驱动辅助工具：

```powershell
./tools/Bind-Fastboot-Driver.ps1 -InstanceId '实际设备实例ID' -InfPath 'C:/drivers/usb_driver/android_winusb.inf'
```

默认仅检查明确的实例和 Google 原始签名 INF；添加 `-Install` 才进行绑定，需管理员权限。

ADB / Fastboot 从 [Android 官方](https://developer.android.com/tools/releases/platform-tools)获取，驱动从 [Google USB Driver](https://developer.android.com/studio/run/win-usb)获取。自行重编 preload 需要 NDK r27c 和 GNU Make；普通材料校验不需要这些编译工具。根权限与 Google Play Integrity Device / Strong 是不同的验证项目。
