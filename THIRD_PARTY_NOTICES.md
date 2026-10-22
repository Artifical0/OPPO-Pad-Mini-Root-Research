# 第三方来源与许可

本仓库原有 OTA 研究工具代码按 GPL-3.0-or-later 发布。第三方文件分别保留原作者、原权利和原许可证，GPL 不重新授权 OPPO 固件、第三方载荷或全部混合材料。

| 组件 | 来源/固定版本 | 说明 |
|---|---|---|
| KernelSU | [tiann/KernelSU v3.3.0](https://github.com/tiann/KernelSU/tree/v3.3.0)、[v3.3.1](https://github.com/tiann/KernelSU/tree/v3.3.1) | 工具和源码快照一同提供，保留各组件 LICENSE / 版权；官方 release 二进制未修改 |
| GBL / ABL 工具源码 | [ditvelo/gbl_root_canoe 2cf345a](https://github.com/ditvelo/gbl_root_canoe/tree/2cf345a299df3f8b7172d6ad2fa5985e67fe53d6) | 固定源码快照、GPL-3.0 文本与本机 extractfv/patch_abl 构建产物一同提供，子目录依其原有通知 |
| 原帖 BDS / BLTools / RebootTools | [原帖](https://www.coolapk.com/feed/73496160) 的 GBL 包 | 原包没有对应构建提交；不能宣称已证明它与上述源码逐字节对应 |
| preload builder / SO | [koaaN/x9u-preload-builder 1880834](https://github.com/koaaN/x9u-preload-builder/tree/18808341a788c2ccb5fb3f071d37d6009c959199) | 源码快照及本机特定固件构建产物；上游未找到独立顶层 LICENSE，不作开源许可补授或跨设备兼容承诺 |
| OPPO 原厂/修补启动镜像 | OPD2515 500 / 17.0.0.103 与原帖旧签名 ABL | 厂商固件及其派生研究材料，不受本仓库 GPL 重新授权；完整 ROM、设备专属 persist 和用户数据不包含 |

源码快照用于固定当时的工具输入和便于审查，并不意味着这里证明了所有上游 release 的可复现构建。发布包只含显式挑选的材料，不含运行时私钥、账号或完整设备诊断包。
