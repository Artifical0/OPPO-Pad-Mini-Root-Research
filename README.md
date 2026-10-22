# OPPO Pad Mini（OPD2515）Root 与 ColorOS 17 升级研究

整理日期：2026-10-22。记录同一台 OPPO Pad Mini 的 **16.0.10.500 首次 root** 和 **500 → 17.0.0.103 保留 GBL / KernelSU 升级**，供复查启动链、工具和失败原因。

| 路线 | 本机结果 | 阅读入口 |
|---|---|---|
| 500 临时提权 → GBL → 真实解锁 → KSU LKM | 完成；正常重启后 UID 0、LKM Live、SELinux Enforcing | [500 root 实测记录](docs/500-root.md) |
| 500 → ColorOS 17.0.0.103 | 完成；首次开机、快照合并、再次正常重启、恢复原 5 个模块后重启通过 | [103 升级记录](docs/17-103-upgrade.md) |
| 旧 OTA Helper 0.1.0-rc2 模块 | 历史研究代码；没有实际安装或 OTA 验证；不适用于此次 3.3.1/uapi 5 状态 | [历史代码说明](OPD2515-OTA-Helper/README.md) |

500 使用的内核是 `6.12.58-android16-6-g7704a1ae279b-ab15213644-4k`；103 使用 `6.12.69-android16-6-g242e1a07f878-ab15865446-4k`。Android 17 的本次内核仍对应 `android16-6.12` KMI。**结论只覆盖本机和这些文件组合，槽位 b → a 也只代表本次升级。** 首次解锁过程中本机进入 Recovery，并经用户确认清除了数据；不能据此承诺无损解锁。

获取材料：

1. 阅读上述两篇记录和[工具清单](docs/tools.md)。
2. 从 [Releases](https://github.com/Artifical0/OPPO-Pad-Mini-Root-Research/releases) 获取 `OPD2515-research-materials-20261022.zip` 与 `SHA256SUMS.txt`，核对摘要后解压到仓库根目录。
3. 二进制包包含本次 SO、GBL/BLTools、两版 KSU 工具、对应 init_boot / EFI、复现测试所用原厂输入、上游源码快照；逐文件来源、用途和 SHA256 见 [materials-manifest.json](materials-manifest.json)。没有自动执行或刷写入口。

```powershell
python -m pip install -r requirements.txt
python tools/verify_materials.py .
python -m unittest discover -s OPD2515-OTA-Helper/tests -p "test_*.py" -v
node OPD2515-OTA-Helper/tests/test_webui.mjs
```

未下载材料时，可运行独立的 payload / 对比解析测试：

```powershell
python -m unittest discover -s OPD2515-OTA-Helper/tests -p "test_payload.py" -v
python -m unittest discover -s OPD2515-OTA-Helper/tests -p "test_compare.py" -v
```

工具运行条件及写入范围见[工具说明](docs/tools.md)，离线检查不能替代设备启动验证。此次公开的是历史记录与电脑端复核结果；整理发布时没有再次对平板提权、改模块、刷分区或重启。

脱敏结果在 [evidence/](evidence/README.md)。不发布 userdata、persist 整分区、聊天/应用备份、keybox、私钥、账号凭据、完整 bugreport 或设备序列号。两份完整固件合计约 18 GB，不在发布包内；保留[固件指纹](docs/firmware.md)，由研究者自行取得相同完整包。

原始研究工具代码采用 GPL-3.0-or-later，见 [LICENSE](LICENSE)。上游源码和第三方二进制保留其原有权利与许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；不能将这里的 GPL 声明理解为 OPPO 固件或全部第三方文件的重新授权。
