# 历史 OTA Helper 与 103 研究工具

**0.1.0-rc2 模块没有真机安装/OTA 验证；本机升级 103 没有使用它。** RC2 固定要求 KSU 3.3.0/uapi 2，不能用于本次 3.3.1/uapi 5 状态，也不是供人直接安装的通用保 root 模块。这里只保存源码、构建器与测试，未将 RC2 安装包作为推荐成品发布。

此次成功的 103 路线和实测边界见[升级记录](../docs/17-103-upgrade.md)。

- `module/`：历史 RC2 实验模块，无开机刷写钩子、自动下载或自动重启。
- `tools/inspect_payload.py`、`compare_payloads.py`、`extract_selected_payload.py`：电脑端完整包分析、比较、提取。
- `tools/verify_ota_zip.py`、`verify_mbn7.py`：离线签名/结构检查，不验证硬件熔丝。
- `tools/guarded_17.py`：本次 500/b → 103/a 的检查/备份/写入事务源码，固定版本、内核、槽位、摘要、KSU/HAL 和更新引擎状态；不能改掉保护条件当成通用脚本。
- `tools/precheck_deferred_17.py`、`activate_deferred_17.py`：本次延期激活分支的历史源码，仍依赖当时的完整本机准备目录和元数据。公开包不包含完整更新器私有数据库，因此不承诺直接运行此分支。
- `tools/verify_boot_17.py`、`recheck_live.py`：当时的只读检查源码，仍有本次工作目录约定。

公开版本将序列号改成显式的 `OPD_SERIAL`，ADB 位置可通过 `OPD_ADB` 设置；未设置序列号会在联系设备前拒绝。计划中的资产路径按仓库根目录解析。版本/槽位/镜像摘要检查保持原有要求。公开源码的哈希不等于当时执行源码的哈希，历史工具摘要只作追溯。

测试依赖 Release 材料包中的原厂输入和本次修补镜像。完整测试在下载、校验并解压材料到仓库根目录后执行；测试不调用 ADB/Fastboot。只有 payload/compare 两组测试可不依赖二进制材料运行。
