# 固件指纹与获取范围

完整固件留在本地，没有上传 Git 历史或 Release；本仓库提供研究涉及的启动材料子集。请自行从设备适用的官方完整包取得输入，不将文件名当作适配证明。

| 完整 ZIP | 字节数 | SHA256 |
|---|---:|---|
| OPPO_Pad_Mini_16.0.10.500_全量包.zip | 8,852,438,875 | `7ea7c2f3660755629298d61669c0d6c2d75a902082825993fa25608f3f59024f` |
| OPD2515_17.0.0.103.zip | 9,214,591,270 | `aeeb3029c64f3a7251bf861325a21388c1817739c8684155ba7daa71f6beb8d5` |

历史检查两包的 ZIP CRC 和整包签名均通过，签名证书 SHA256 为 `2de09468859e8f347c52149c319ad83046d6a0e1e11ad89b69ffcf8c35aaac6a`。未将离线证书检查等同于设备熔丝/信任根验证；官方更新器对包的接受是另一个检查层。

```powershell
python OPD2515-OTA-Helper/tools/inspect_payload.py --help
python OPD2515-OTA-Helper/tools/extract_selected_payload.py --help
python OPD2515-OTA-Helper/tools/verify_ota_zip.py --help
```

`verify_ota_zip.py` 会读取完整包并验证签名及条目 CRC，耗时取决于磁盘速度。提取工具核对 payload 声明的长度与摘要，只支持它明确实现的操作类型；不支持的增量/未知类型会拒绝。不同槽位的镜像和不同长度的 ABL 范围可能产生不同摘要；必须同时记录比较范围。
