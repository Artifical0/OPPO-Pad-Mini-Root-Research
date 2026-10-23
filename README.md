# OPPO Pad Mini Root 与系统升级指南

适用机型：**OPD2515 / OP6548L1**。这里提供 500 首次 root、500 升级 ColorOS 17.0.0.103 的已验证路线，以及后续 OTA 助手的源码与研究预览版。

| 你的情况 | 从这里开始 | 验证情况 |
|---|---|---|
| 还在 16.0.10.500，准备首次 root | [500 Root 指南](docs/500-root.md) | 本机完成解锁、KSU root 和普通重启 |
| 已有 GBL、真实解锁和 KSU，准备升 103 | [500 → 103 升级指南](docs/17-103-upgrade.md) | 本机首次启动、快照合并和再次重启通过 |
| 已有 root，研究后续官方更新 | [OTA 助手使用说明](ota-helper/README.md) | 0.2.0-rc1 研究预览；离线验证，尚无真机安装及 OTA 验证 |

首次解锁会清除数据，请先备份。后续升级方向由设备实际槽位决定；本机的 `b → a` 不是固定规则。

## 获取工具和材料

在 Windows 安装 [Python 3.11+](https://www.python.org/downloads/) 和 [ADB / Fastboot](https://developer.android.com/tools/releases/platform-tools)，下载或克隆本仓库，在仓库根目录打开 PowerShell：

```powershell
git clone https://github.com/Artifical0/OPPO-Pad-Mini-Root-Research.git
cd OPPO-Pad-Mini-Root-Research
python -m pip install -r requirements.txt
python tools/fetch_materials.py
python tools/verify_materials.py .
```

`fetch_materials.py` 下载固定版本的研究材料，并校验压缩包摘要；最后一条命令逐项核对材料。它们只操作电脑文件。也可从 [材料 Release](https://github.com/Artifical0/OPPO-Pad-Mini-Root-Research/releases/tag/research-2026-10-22-r1) 手动下载、校验并解压到仓库根目录。

- [工具索引](docs/tools.md)：每个文件的用途与完整路径。
- [固件指纹](docs/firmware.md)：500 / 103 完整包的长度、SHA256 和检查工具。完整 ROM 需自行获取。
- [OTA 助手预览版](https://github.com/Artifical0/OPPO-Pad-Mini-Root-Research/releases/tag/ota-helper-v0.2.0-rc1)：模块下载、源码和构建摘要；不能保证所有未来更新保留 root。
- [验证记录](evidence/README.md)：脱敏的 root、系统启动与重启结果。

## 后续更新的工作方式

每次更新都使用“**新的启动备份 + 当前完整包 + 目标完整包**”生成专用保留包。官方 OTA 安装完成并进入真正的待重启状态后，再手动检查和保留；模块不会自动切槽或重启。

目前预览版仅接受 39 项底层固件、XBL / xbl_config、ABL 认证元数据和 KMI 均满足保守兼容条件的更新。底层固件变化需要单独研究，不能沿用旧批准包。本机 500 → 103 的成功属于专门适配的已验证路线，和这个新模块的验证情况分别记录。

后续材料与更新通知：[Telegram @ByteJuno](https://t.me/ByteJuno)。

原始研究代码采用 [GPL-3.0-or-later](LICENSE)。第三方工具、源码和固件材料按各自许可使用，见 [第三方声明](THIRD_PARTY_NOTICES.md)。公开材料不含 userdata、完整 persist、账号凭据、keybox 或私钥。
