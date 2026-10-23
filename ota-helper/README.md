# OPD2515 OTA 助手 0.2.0-rc1

[返回首页](../README.md) · [已验证的 500 → 103 路线](../docs/17-103-upgrade.md)

这是为后续更新准备的 **KernelSU 模块研究预览版**：升级前导出启动备份，电脑审查官方完整包，重启前手动保留目标槽的 KSU 与 GBL。已经实现离线构建、校验和模拟分区事务测试，**尚未在平板安装，也没有下一版 OTA 的真机验证**。

下载：[0.2.0-rc1 Release](https://github.com/ByteJuno/OPPO-Pad-Mini-Root-Research/releases/tag/ota-helper-v0.2.0-rc1)。同页提供 `SHA256SUMS.txt` 和构建清单。旧 `OPD2515-OTA-Helper/` 目录保留历史解析器和专用 103 工具；新版模块源码在本目录 `module/`。

## 能支持哪些更新

| 条件 | 本版要求 |
|---|---|
| 设备 | OPD2515，真实解锁，已部署本文对应的 GBL / BDS / 旧签名 ABL |
| KSU | 3.3.0 / uapi 2 或 3.3.1 / uapi 5，LKM Live；本次生成与当前版本一致 |
| KMI | `6.12-android16-6`，LKM 选择 `android16-6.12` |
| 固件包 | 当前、目标两个官方完整 OTA；同一已固定的 OPPO 签名证书，整包签名与 CRC 通过 |
| 启动链 | XBL / xbl_config 的认证范围不变，ABL 的认证元数据、ARB 和证书链不变 |
| 底层固件 | 完整 39 项清单齐全，当前包与目标包均不变；设备两槽也必须与清单一致 |
| 写入时机 | 官方更新器已激活另一个槽，UpdateEngine 状态 6，快照状态允许写入 |

这个范围刻意保守。很多官方更新会修改底层固件，届时工具会拒绝生成保留包，需要重新适配；**无法靠一个常驻模块保证未知未来版本都能保留 root**。本模块不支持增量 OTA、降级或自动延期激活，也不拦截系统重启。请先关闭系统提供的自动安装和自动重启选项。

## 每次更新怎么做

### 1. 安装预览版，导出新备份

在 KernelSU 管理器中从 ZIP 安装模块。安装过程只放置工具，不写启动分区或 EFI。模块 id 为 `opd2515_ota_helper`，与旧 RC2 相同；已有旧版时会作为替换安装，旧保留包必须重新生成。

停用其他第三方模块，处理完排队的模块更新后重启，确认系统和 root 正常、上一轮快照合并结束。打开本模块 WebUI，点击“刷新状态”，再点“备份并导出”。

输出：`Download/OPD2515-OTA/export-日期时间.tar.gz`，同目录有压缩包摘要。将这份**本次新导出的备份**复制到电脑。它包含启动镜像和菜单，不包含应用数据，也不包含完整 persist。

### 2. 在电脑生成本次保留包

需要 Windows、Python 3.11+，以及[首页步骤](../README.md#获取工具和材料)下载的固定研究材料。当前完整包必须对应设备正在运行的版本，目标完整包必须是准备安装的新版本。

在仓库根目录运行；三个输入路径替换成自己的文件，输出目录必须不存在：

```powershell
New-Item -ItemType Directory -Path C:/opd2515-temp -Force
python ota-helper/prepare_update.py `
  --baseline 'C:/OTA/export-日期时间.tar.gz' `
  --current-package 'C:/OTA/当前完整包.zip' `
  --target-package 'C:/OTA/目标完整包.zip' `
  --out './update-output-本次版本' `
  --temp-root 'C:/opd2515-temp'
```

提取和补丁工具使用纯英文临时路径；仓库本身可在中文目录。若本机需要 MinGW64 DLL，安装相应运行库，并增加 `--runtime-dir 'C:/msys64/mingw64/bin'`。两个完整包会被逐字节读取，耗时取决于磁盘速度。

检查通过后得到：

| 输出 | 用途 |
|---|---|
| `OPD2515-OTA-approved.zip` | 仅供本次备份、源槽、目标槽和新固件使用的保留包 |
| `OPD2515-OTA-approved.zip.sha256` | WebUI 导入时填写的 64 位小写 SHA256 |
| `review-report.json` | 包签名、版本、槽位与静态兼容性检查结果 |
| `target-images/` 与补丁日志 | 留在电脑用于复核的材料 |

只有成功输出保留包和报告才继续；`BLOCKED` 表示本次不在支持范围，不能删除检查条件强行生成。输出可能含自己的本地路径，分享前先检查。

### 3. 导入并完成官方安装

把保留包放到平板 **Download 根目录**，保持文件名 `OPD2515-OTA-approved.zip`。在 WebUI 粘贴电脑输出的 SHA256，点击“校验并导入”。

通过官方本地安装入口安装**刚才审查的目标完整包**，完成后停在重启前。回到模块，点击“检查 OTA 和目标槽位”。若更新器仍为 IDLE、下次启动仍是当前槽，模块会停止；需按该版本单独审查更新器的激活流程。

### 4. 检查通过后手动保留

WebUI 显示 READY 后，输入结果中的 `APPLY_a` 或 `APPLY_b`，再点击保留。模块会：

1. 再次核对设备、KSU、真实槽位、OTA 和完整固件清单。
2. 备份目标槽原厂 init_boot、完整 ABL 与现用 Normal EFI，并核对摘要。
3. 只写**目标槽** init_boot、ABL，以及共享 persist 中的 `ABL_normal.efi`；保留菜单原字节。
4. 同步、逐项回读，确认源槽和 OTA 状态仍符合计划，最后输出 SUCCESS。

不会写源槽、XBL、BDS、ARB 或用户数据，也不会自动设置槽位、锁 BL、重启。底层固件保持由官方 OTA 管理。

事务记录和写入前备份保存在 `/data/adb/opd2515_ota_helper/transaction-*`。写入中断会尝试在源槽和 OTA 状态仍符合条件时恢复本次修改；这不能撤销整个 OTA。出现报错、等待超时或回读不符时保持当前系统运行，保留事务目录和日志，先核对状态再安排后续操作。

### 5. 重启验收

SUCCESS 后自行重启，确认 GBL 和新系统正常、KSU 能授权 Shell root。等待快照合并结束，再做一次普通重启；最后逐项恢复第三方模块。每次 OTA 都要从步骤 1 重新导出并生成保留包，不能复用上次 ZIP。

## 从源码构建与验证

构建模块不需要下载 ROM 或研究材料，不包含预置启动镜像：

```powershell
python ota-helper/build.py
```

产物位于 `ota-helper/dist/`，相同源码产生相同 ZIP 字节。离线验证需要先获取研究材料：

```powershell
python -m unittest discover -s ota-helper/tests -p 'test_*.py' -v
node ota-helper/tests/test_webui.mjs
```

Linux CI 还运行完整 39 项模拟固件的 shell 事务测试，覆盖状态门槛、写入、读回和回退。模拟分区是普通文件；这些结果不能替代设备上的真机 OTA 验收。验证状态见 [VALIDATION.md](VALIDATION.md)。
