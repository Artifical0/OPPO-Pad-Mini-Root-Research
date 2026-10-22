"""List partitions declared by Android OTA metadata. No flashing or extraction.

Reads only the ZIP directory and bounded payload metadata, not the multi-GB blobs.
Unknown containers and partition-less payloads are never classified as safe.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import pathlib
import re
import struct
import zipfile

LIMIT = 32 * 1024 * 1024
CRITICAL = {"boot", "init_boot", "vendor_boot", "recovery", "abl", "xbl", "xbl_config", "xbl_ramdump",
            "efisp", "persist", "dtbo", "vbmeta", "vbmeta_system", "vbmeta_vendor", "frp", "misc"}
SYSTEM = {"system", "system_ext", "product", "vendor", "odm", "system_dlkm", "vendor_dlkm", "odm_dlkm",
          "my_product", "my_engineering", "my_stock", "my_heytap", "my_carrier", "my_region", "my_bigball", "my_manifest"}


def require(value, message):
    if not value:
        raise ValueError(message)


def varint(data, pos):
    result = 0
    for shift in range(0, 70, 7):
        require(pos < len(data), "截断的 protobuf varint")
        byte = data[pos]; pos += 1
        require(shift < 63 or byte <= 1, "protobuf varint 溢出")
        result |= (byte & 127) << shift
        if byte < 128:
            return result, pos
    raise ValueError("protobuf varint 过长")


def fields(data):
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        number, wire = tag >> 3, tag & 7
        require(number > 0, "protobuf 字段编号无效")
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            require(pos + size <= len(data), "截断的 protobuf 定长字段")
            value = data[pos:pos + size]; pos += size
        elif wire == 2:
            size, pos = varint(data, pos)
            require(size <= len(data) - pos, "protobuf 字段越界")
            value = data[pos:pos + size]; pos += size
        else:
            raise ValueError("不支持的 protobuf wire type")
        yield number, wire, value


def one(data, number, wire, default=None):
    result = [value for n, w, value in fields(data) if n == number and w == wire]
    require(len(result) <= 1, "重复的单值 protobuf 字段")
    return result[0] if result else default


def partition_info(data):
    if data is None:
        return None
    digest = one(data, 2, 2)
    require(digest is None or len(digest) == 32, "分区摘要不是 SHA256")
    return {"bytes": one(data, 1, 0), "sha256": digest.hex() if digest is not None else None}


def parse_manifest(manifest):
    block_size = one(manifest, 3, 0, 4096)
    minor = one(manifest, 12, 0, 0)
    require(block_size in (512, 1024, 2048, 4096, 8192, 16384), "未知 payload block_size")
    partitions, seen = [], set()
    for number, wire, data in fields(manifest):
        if number != 13 or wire != 2:
            continue
        raw = one(data, 1, 2)
        require(raw is not None, "缺少分区名称")
        name = raw.decode("ascii")
        require(re.fullmatch(r"[a-zA-Z0-9_]+", name) and name not in seen, "无效或重复的分区名称")
        seen.add(name)
        ops = collections.Counter()
        uses_source = False
        for n, w, operation in fields(data):
            if n == 8 and w == 2:
                kind = one(operation, 1, 0)
                require(kind is not None, "缺少操作类型")
                ops[kind] += 1
                if kind not in (0, 1, 6, 7, 8):
                    uses_source = True
        base = re.sub(r"_[ab]$", "", name)
        category = "boot_chain" if base in CRITICAL else "system" if base in SYSTEM else "firmware_or_other"
        partitions.append({"name": name, "category": category,
                           "old": partition_info(one(data, 6, 2)), "new": partition_info(one(data, 7, 2)),
                           "operations": dict(ops), "uses_source_data": uses_source})
    require(partitions, "payload 没有可识别分区；不推断为组件更新")
    source_required = any(p["old"] or p["uses_source_data"] for p in partitions)
    return {"block_size": block_size, "minor_version": minor,
            # OPlus's real full 500 package declares minor=9 but contains only
            # replacement/zero operations and no old-partition checks. Report
            # data dependency rather than guessing from the minor number.
            "full_or_delta": "source_dependent" if source_required else "self_contained",
            "requires_source_partition_data": source_required,
            "partitions": partitions,
            "boot_chain_declared": [p["name"] for p in partitions if p["category"] == "boot_chain"],
            "other_firmware_declared": [p["name"] for p in partitions if p["category"] == "firmware_or_other"]}


def read_payload(stream):
    header = stream.read(20)
    require(len(header) == 20 and header[:4] == b"CrAU", "不是 Android payload 头")
    version, size = struct.unpack_from(">QQ", header, 4)
    require(version == 2 and 0 < size <= LIMIT, "payload 版本或元数据长度不支持")
    signature_size = stream.read(4)
    require(len(signature_size) == 4, "payload 头截断")
    sig_len = struct.unpack(">I", signature_size)[0]
    require(sig_len <= 1024 * 1024, "元数据签名过大")
    manifest = stream.read(size)
    require(len(manifest) == size, "payload manifest 截断")
    result = parse_manifest(manifest)
    result.update(payload_major_version=version, manifest_bytes=size,
                  manifest_sha256=hashlib.sha256(manifest).hexdigest(), metadata_signature_bytes=sig_len)
    return result


def inspect(path):
    report = {"file": str(path), "bytes": path.stat().st_size, "safety_decision": "NOT_AUTHORIZED_TO_FLASH_OR_REBOOT",
              "signature_verified": False, "note": "Partition declarations alone do not prove compatibility or authenticity."}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            candidates = [i for i in archive.infolist() if i.filename in ("payload.bin", "payload_metadata.bin")]
            report["container"] = "zip"
            meta = [i for i in archive.infolist() if i.filename == "META-INF/com/android/metadata"]
            require(len(meta) <= 1, "重复的 OTA metadata")
            if meta:
                require(meta[0].file_size <= 65536, "OTA metadata 过大")
                text = archive.read(meta[0]).decode("utf-8")
                report["ota_metadata"] = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
            if not candidates:
                report.update(classification="UNKNOWN_CONTAINER_OR_COMPONENT_UPDATE", payload_found=False)
                return report
            require(len({i.filename for i in candidates}) == len(candidates), "重复 payload 条目")
            selected = next((i for i in candidates if i.filename == "payload.bin"), candidates[0])
            with archive.open(selected) as stream:
                report.update(read_payload(stream))
    else:
        report["container"] = "raw_payload_or_metadata"
        with path.open("rb") as stream:
            report.update(read_payload(stream))
    report["payload_found"] = True
    report["classification"] = "BOOT_OR_FIRMWARE_UPDATE" if report["boot_chain_declared"] or report["other_firmware_declared"] else "SYSTEM_PARTITIONS_DECLARED"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        require(not args.out.exists(), "报告已存在，请换新文件名")
        report = inspect(args.package)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("分类：", report["classification"])
        print("启动分区：", ", ".join(report.get("boot_chain_declared", [])) or "未列出；仍需结合设备状态判断")
        print("报告：", args.out)
        print("这是只读清单检查，不是重启或刷写许可。")
    except (ValueError, OSError, UnicodeError, zipfile.BadZipFile) as error:
        parser.exit(1, "UNKNOWN/BLOCKED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
