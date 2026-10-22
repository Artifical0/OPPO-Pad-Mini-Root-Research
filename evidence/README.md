# 证据说明

这里发布的是 2026-10-12 / 14 当时保存记录的脱敏副本，2026-10-22 从原始文件重新读取后整理。序列号、启动 UUID、本机路径及完整 bootconfig 已移除或缩减，不能对脱敏文件套用原始文件摘要。`source-index.json` 记录原始相对路径和原始摘要，供持有原文件的人核对；它本身不构成设备远程证明。

- `500/gbl-deployment.json`：启动链部署与用户确认 GBL，状态停在解锁流程中间；不能单独作为最终 root 证明。
- `500/ksu-after-normal-reboot.json`：首次 KSU 安装后的正常重启验证。
- `17-103/first-boot.json`、`second-boot.json`、`modules-enabled-boot.json`：103 首次启动、再次普通重启、恢复原 5 个模块后的重启检查。
- `17-103/completed.json`：汇总及用户确认的数据可用情况；不是逐个应用数据一致性检测。
- `17-103/prepare-plan.json`：执行前的版本/槽位/哈希计划，路径已改为仓库相对路径。其 runtime_verified=false 是准备时状态；完成结果以之后的开机记录为准。

`materials-manifest.json` 的摘要在此次整理时从实际二进制重新计算。原始 bugreport、persist、完整设备备份、keybox、私钥及应用配置没有发布。

公开 payload 报告只将本机绝对路径改成文件名；公开计划中的 target_report_sha256 随之重新计算。分区声明、镜像摘要、版本和槽位条件保持原始记录。测试中的 500 fixture 只有真实包的 payload 元数据，没有操作数据，不能安装或刷写。
