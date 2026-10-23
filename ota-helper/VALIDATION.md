# 0.2.0-rc1 验证范围

本版增加了 KSU 3.3.1 / uapi 5、schema 2 备份、扩展菜单、原始 bootconfig、只读 Boot HAL 和完整 39 项固件门槛。每个保留包绑定当前启动镜像、KSU、菜单、固件与槽位。

| 检查层 | 覆盖范围 |
|---|---|
| Python | 备份解析、归档成员、签名证书固定、菜单、完整包清单、固件变化拒绝、专用包格式、确定性构建 |
| Windows 本地补丁 | 真实 500 原厂 ABL / init_boot，经已固定摘要的工具生成 Normal EFI 与 KSU 3.3.1 镜像 |
| Shell 模拟事务 | 普通文件模拟两槽；真实生产校验、39 项固件、读回、事务备份、状态门槛、回退 |
| WebUI mock | 参数校验、命令引用、回调清理、超时和按钮状态 |
| GitHub Actions | 每次提交运行解析测试、WebUI、shell 事务和模块构建 |

未验证：KernelSU 管理器真机安装、Android BusyBox / Binder 的完整集成、下一版官方 OTA、模块导致的真实启动结果、突然断电后的恢复。

本版不是 500 → 103 实测使用过的模块，不能将历史设备成功当成本版验收结果。底层固件变化的 OTA 不在支持范围。

2026-10-23 本地结果：46 项历史 Python 测试和 10 项新版 Python 测试全部通过，两套 WebUI mock 通过；Linux BusyBox 1.37 的完整 39 项模拟固件事务、状态门槛和回退通过。500、103 两个完整包的整包签名、CRC 与固定证书校验通过，38 项发布材料摘要通过。

持续验证：[GitHub Actions](https://github.com/ByteJuno/OPPO-Pad-Mini-Root-Research/actions/workflows/offline-checks.yml)。安装及更新的实际设备集成仍需单独验证。
