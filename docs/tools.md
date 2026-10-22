# 工具与材料索引

Release 材料包保留与研究脚本一致的目录结构，解压到仓库根目录。所有二进制的实际大小、SHA256、来源和用途见 [materials-manifest.json](../materials-manifest.json)。`python tools/verify_materials.py .` 逐项复核；下载或解压不会自动运行载荷、安装驱动或写平板。

| 工具/材料 | 对应版本/用途 | 发布位置 |
|---|---|---|
| 本机编译 preload.so | 固定 500 输入的临时提权产物，存在 panic/检测重启历史 | Release：`root-work/preload-release/` |
| x9u-preload-builder 源码 | `18808341a788c2ccb5fb3f071d37d6009c959199`，用于重新生成 target.h 和 SO | Release：`sources/`，另见上游固定链接 |
| BDS、BLTools、RebootTools、原工具菜单 | 首次 GBL 入口和真实解锁；ArbTools 为原子菜单随附文件，本次未使用 | Release：`root-work/gbl/deploy-original-20261012_144259/payload/` |
| 旧签名 ABL | 1 MiB 的 GBL 入口分区镜像 | Release：`root-work/coolapk-original/oppo_pad_mini_root_file/abl_a.img` |
| 500 / 103 Normal EFI | 分别由各自原厂 ABL 生成，不能互换或直接当完整 ABL 刷写 | Release：`root-work/gbl/compatibility-.../current_b/`、`root-work/ColorOS17-17.0.0.103-analysis/candidates-offline/` |
| KernelSU 3.3.0 / 3.3.1 | 官方 ksud Windows、ksuinit、android16-6.12 LKM 与管理器 | Release：`root-work/tools/`、`root-work/ColorOS17-17.0.0.103-analysis/ksu-3.3.1-tools/` |
| 500 / 103 KSU init_boot | 本机实际使用的特定镜像与原厂输入，不是跨版本通用包 | Release：对应 `patched/`、`candidates-offline/`、`images-17/` |
| extractfv / patch_abl Windows | 提取 LinuxLoader 并生成 Normal EFI | Release：`root-work/gbl-source/submodules/*/build/`，固定源码快照在 `sources/` |
| ADB/Fastboot、Google USB Driver | USB 通信和明确设备实例的驱动绑定 | 从 [Android 官方](https://developer.android.com/tools/releases/platform-tools)及[Google USB Driver](https://developer.android.com/studio/run/win-usb)获取，未重打包 SDK |
| NDK r27c / GNU Make 4.4.1 | 编译匹配固件的 preload，不是执行 root 所需驻留软件 | 从官方工具链和 MSYS2 获取，未打包整个 SDK |
| Python 3.11+、cryptography、Node.js、Bash | 离线解析、校验与测试 | `requirements.txt`；测试 shell 推荐 Git Bash |
| OTA 检查/提取/事务源码 | 本次自建工具与历史 RC2 | 仓库 `OPD2515-OTA-Helper/` |
| 驱动绑定辅助脚本 | `VID_18D1&PID_D00D`，签名检查、限定实例 | 仓库 `tools/Bind-Fastboot-Driver.ps1` |

## 离线研究

```powershell
python -m pip install -r requirements.txt
python tools/verify_materials.py .
python OPD2515-OTA-Helper/tools/inspect_payload.py --help
python OPD2515-OTA-Helper/tools/compare_payloads.py --help
python OPD2515-OTA-Helper/tools/extract_selected_payload.py --help
python -m unittest discover -s OPD2515-OTA-Helper/tests -p "test_*.py" -v
node OPD2515-OTA-Helper/tests/test_webui.mjs
```

部分旧 `review.py` 参数仍提供原 Windows 工具链位置作为默认值，移植时用其 `--git`、`--mingw-bin`、`--tool-temp-root` 等显式参数；它们不是必须使用的盘符。构建 RC2 还要求固定 GBL 工具和 KSU 3.3.0，不能把它打包成功视为已适用于 103。

## 设备工具的运行边界

`guarded_17.py check` 是读取平板；`apply` 会写目标 init_boot、ABL 和共享 persist 中的 EFI/菜单，并使用原有备份与回读保护。`activate_deferred_17.py` 会通过系统 UpdateEngine 激活已认证待启动槽并暂停更新 UI，它不是普通只读工具。二者不应与离线测试混淆。

公开源码保留本次 b → a 的严格检查，并要求显式设备参数：

```powershell
$env:OPD_ADB = 'C:/Android/Sdk/platform-tools/adb.exe'
$env:OPD_SERIAL = '填写自己 adb devices 中的序列号'
python OPD2515-OTA-Helper/tools/guarded_17.py --help
```

修改环境变量只选择设备，不会让不匹配的固件通过。这里不提供跳过检查或固定 a/b 的通用刷写包装器。原公开计划含本次设备分区拓扑，其他设备需独立核对；不要为通过检查而机械替换摘要。

驱动脚本不包含本机 Driver Store 路径，先指定实际设备实例和已下载的原始签名 INF：

```powershell
./tools/Bind-Fastboot-Driver.ps1 -InstanceId '实际设备实例ID' -InfPath 'C:/drivers/usb_driver/android_winusb.inf'
```

默认只枚举并验证。明确添加 `-Install` 才绑定，安装需管理员权限。该流程只针对 D00D，本次没有修改 INF 或禁用 Windows 签名验证。

本仓库未发布或研究私钥/keybox 导出与替换。KSU root 成功也不代表 Google Play Integrity Device/Strong 通过。
