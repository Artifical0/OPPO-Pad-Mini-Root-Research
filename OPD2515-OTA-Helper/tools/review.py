"""Offline OPD2515 OTA review and packet builder. Never contacts or writes a device."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import pathlib
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from inspect_payload import inspect as inspect_ota

PROJECT = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
VERSION = "0.1.0-rc2"
OLD_HASH = "0210487cbc59bdcdb03bb2ee61d9d80fffad8f2ccf35bc7d28d7d9569ad59802"
BDS_HASH = "d485e2de52ef7827fd6c5f6b1c56357da422f9a43f86e10b46a945bd17a4e49c"
TOOL_HASHES = {
    "ksud-x86_64-pc-windows-gnu.exe": "f9880fbbb3751d847dd1fbe3ea5939f592c28887ff274cd5ddb090ed6c751ee0",
    "lkm-aarch64-android16-6.12_kernelsu.ko": "877286f81d500c4ec546c96e9718c186b7379573c97ba5d5a35dd9a91465d076",
    "ksuinit-aarch64": "b49fff3252cdcd14bf80472becbd96c4f17028a632b364e8d455d335b94f1345",
}
FIRMWARE_NAMES = {
    "engineering_cdt", "uefi", "aop", "aop_config", "tz", "hyp", "modem", "bluetooth", "dsp",
    "keymaster", "spuservice", "devcfg", "qupfw", "uefisecapp", "imagefv", "shrm", "cpucp", "featenabler",
    "oplus_sec", "splash", "cpucp_dtb", "soccp_debug", "soccp_dcd", "pdp", "pdp_cdb", "tme_seq_patch",
    "hyp_ac_config", "multiimgoem", "tme_fw", "soccp", "multiimgqti", "tme_config", "xbl_ac_config",
    "secretkeeper", "tz_ac_config", "tz_qti_config", "dcp", "pvmfw", "xbl_ramdump",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def elf_segments(data: bytes):
    require(data[:4] == b"\x7fELF" and data[5:6] == b"\x01", "不是小端 ELF，停止")
    cls = data[4]
    require(cls in (1, 2) and len(data) >= 64, "ELF 类型或长度异常")
    if cls == 1:
        phoff = struct.unpack_from("<I", data, 28)[0]
        phsize, count = struct.unpack_from("<HH", data, 42)
        fmt, minimum = "<IIIIIIII", 32
    else:
        phoff = struct.unpack_from("<Q", data, 32)[0]
        phsize, count = struct.unpack_from("<HH", data, 54)
        fmt, minimum = "<IIQQQQQQ", 56
    require(0 < count <= 128 and phsize == minimum and phoff + count * phsize <= len(data), "ELF 程序头越界")
    segments = []
    for index in range(count):
        values = struct.unpack_from(fmt, data, phoff + index * phsize)
        if cls == 1:
            kind, off, _va, _pa, size, _mem, flags, _align = values
        else:
            kind, flags, off, _va, _pa, size, _mem, _align = values
        require(off <= len(data) and size <= len(data) - off, "ELF 段越界")
        segments.append(dict(index=index, kind=kind, off=off, size=size, flags=flags))
    end = max([phoff + count * phsize] + [s["off"] + s["size"] for s in segments])
    return segments, end


def canonical(data: bytes) -> bytes:
    # Authenticated headers and all segment bytes are included. Only unused tail padding is excluded.
    _, end = elf_segments(data)
    return data[:end]


def der_object(data: bytes, pos=0):
    require(pos + 2 <= len(data) and data[pos] == 0x30, "DER 对象异常")
    value = data[pos + 1]
    if value < 128:
        header, size = 2, value
    else:
        width = value & 127
        require(1 <= width <= 3 and pos + 2 + width <= len(data), "DER 长度异常")
        header = 2 + width
        size = int.from_bytes(data[pos + 2:pos + header], "big")
    require(pos + header + size <= len(data), "DER 对象越界")
    return data[pos:pos + header + size]


def authenticate_abl(data: bytes):
    segments, _ = elf_segments(data)
    candidates = [s for s in segments if (s["flags"] >> 24) & 7 == 2]
    require(len(candidates) == 1, "ABL hash 段数量异常")
    hs = candidates[0]
    h = data[hs["off"]:hs["off"] + hs["size"]]
    require(len(h) >= 40, "ABL hash 段过短")
    _, version, common_len, qm, om, ht, qs, qc, osig, oc = struct.unpack_from("<10I", h)
    require(version == 7 and (qm, qs, qc) == (0, 0, 0), "只支持已验证的 OEM-only MBNv7 ABL")
    require(common_len == 24 and om == 224 and ht == len(segments) * 48, "ABL 元数据布局变化")
    table_start = 40 + common_len + om
    sig_start, cert_start = table_start + ht, table_start + ht + osig
    require(cert_start + oc == len(h), "ABL hash 段边界变化")
    signature = der_object(h[sig_start:cert_start])
    require(not any(h[sig_start + len(signature):cert_start]), "签名填充异常")
    certdata = h[cert_start:]
    chain, encoded, pos = [], [], 0
    while pos < len(certdata) and certdata[pos] == 0x30:
        obj = der_object(certdata, pos)
        encoded.append(obj)
        chain.append(x509.load_der_x509_certificate(obj))
        pos += len(obj)
    padding = certdata[pos:]
    require(len(chain) == 3 and (not any(padding) or all(x == 255 for x in padding)), "证书链布局变化")
    for i in range(2):
        require(chain[i].issuer == chain[i + 1].subject, "证书链 issuer 不符")
        chain[i + 1].public_key().verify(chain[i].signature, chain[i].tbs_certificate_bytes, ec.ECDSA(chain[i].signature_hash_algorithm))
    chain[0].public_key().verify(signature, h[:sig_start], ec.ECDSA(hashes.SHA384()))
    for s in segments:
        digest = bytes(48) if s is hs else hashlib.sha384(data[s["off"]:s["off"] + s["size"]]).digest()
        require(h[table_start + s["index"] * 48:table_start + (s["index"] + 1) * 48] == digest, "ABL 已签名段被修改")
    common, oem = h[40:40 + common_len], h[40 + common_len:table_start]
    return dict(common=common.hex(), oem=oem.hex(), chain=[sha(c) for c in encoded], chain_padding_hash=sha(padding),
                arb=struct.unpack_from("<I", oem, 8)[0], signature_verified=True, segments_verified=True)


def boot_header(data, init=False):
    require(len(data) >= 4096 and data[:8] == b"ANDROID!", "不是 Android boot 镜像")
    kernel, ramdisk, os_version, header_size = struct.unpack_from("<4I", data, 8)
    version = struct.unpack_from("<I", data, 40)[0]
    require(version == 4 and header_size == 1584, "只支持 boot header v4")
    require(4096 + ((kernel + 4095) // 4096) * 4096 + ramdisk <= len(data), "boot 内容越界")
    require((kernel == 0 and ramdisk > 0) if init else kernel > 0, "boot/init_boot 类型错误")
    return dict(kernel_bytes=kernel, ramdisk_bytes=ramdisk, os_version=os_version)


def kernel_release(data):
    header = boot_header(data)
    kernel = data[4096:4096 + header["kernel_bytes"]]
    if kernel[:2] == b"\x1f\x8b":
        # Bound decompression before scanning version strings.
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(kernel)) as stream:
            kernel = stream.read(128 * 1024 * 1024 + 1)
        require(len(kernel) <= 128 * 1024 * 1024, "压缩内核过大")
    releases = set(re.findall(rb"Linux version ([0-9][^\s\x00]{0,180})", kernel))
    require(len(releases) == 1, "无法唯一识别目标内核版本；不自动猜测")
    release = releases.pop().decode("ascii")
    match = re.fullmatch(r"(\d+)\.(\d+)\.\d+-android(\d+)-(\d+)-.+", release)
    require(match is not None, "无法识别 GKI KMI")
    kmi = f"{match[1]}.{match[2]}-android{match[3]}-{match[4]}"
    require(kmi == "6.12-android16-6", f"KMI 已变化：{kmi}，本版停止")
    return release


def read_kv(data):
    result = {}
    for line in data.decode("utf-8").splitlines():
        key, sep, value = line.partition("=")
        require(sep == "=" and key not in result and re.fullmatch(r"[a-z][a-z0-9_]*", key), "元数据字段异常")
        require("=" not in value and "\r" not in value, "元数据值异常")
        result[key] = value
    return result


def read_baseline(path):
    names = {"boot.img", "init_boot.img", "abl.img", "xbl.img", "xbl_config.img", "ABL_normal.efi", "BOOTENTRIES", "device.txt", "SHA256SUMS"}
    if path.is_dir():
        blobs = {n: (path / n).read_bytes() for n in names}
    else:
        blobs = {}
        with tarfile.open(path, "r:gz") as tar:
            for member in tar:
                name = member.name.removeprefix("./")
                if name in (".", "") and member.isdir():
                    continue
                require(name in names and name not in blobs and member.isfile(), "备份包含异常路径、链接或重复成员")
                require(member.size <= 128 * 1024 * 1024, "备份成员过大")
                blobs[name] = tar.extractfile(member).read()
        require(set(blobs) == names, "备份文件不完整")
    sums = {}
    for line in blobs["SHA256SUMS"].decode().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.strip().removeprefix("*")
        require(name in names - {"SHA256SUMS"} and name not in sums and re.fullmatch("[0-9a-f]{64}", digest), "备份摘要表异常")
        require(sha(blobs[name]) == digest, f"备份损坏：{name}")
        sums[name] = digest
    require(set(sums) == names - {"SHA256SUMS"}, "备份缺少摘要")
    meta = read_kv(blobs["device.txt"])
    require(meta.get("schema") == "1" and meta.get("model") == "OPD2515", "备份型号不符")
    require((meta.get("active_slot"), meta.get("target_slot")) in (("a", "b"), ("b", "a")), "备份槽位异常")
    require(sha(blobs["abl.img"]) == OLD_HASH and meta.get("bds_hash") == BDS_HASH, "备份启动链不是已验证组合")
    for name in ("boot", "init_boot", "abl", "xbl", "xbl_config"):
        size = len(blobs[name + ".img"])
        require(str(size) == meta.get("size_" + name) == meta.get("target_size_" + name), f"A/B 分区容量不一致：{name}")
    require(kernel_release(blobs["boot.img"]) == meta["kernel"], "备份内核与系统报告不符")
    boot_header(blobs["init_boot.img"], init=True)
    require(blobs["BOOTENTRIES"] == b"Normal Boot:ABL_normal.efi\n%Android Tools:tools\\ENTRIES\n", "当前启动菜单不同于本次已验证配置")
    validate_pe(blobs["ABL_normal.efi"])
    return blobs, meta


def validate_pe(data):
    require(data[:2] == b"MZ" and len(data) >= 64, "EFI 不是 PE 文件")
    off = struct.unpack_from("<I", data, 60)[0]
    require(off + 26 <= len(data) and data[off:off + 4] == b"PE\0\0", "EFI PE 头异常")
    require(struct.unpack_from("<H", data, off + 4)[0] == 0xAA64, "EFI 不是 AArch64")


def make_plan(baseline, meta, target, build):
    require(re.fullmatch(r"OPD2515_[0-9A-Za-z_.()/-]+", build) is not None and build != meta["build"], "需要不同于当前版本的完整 OPD2515 目标版本号")
    old_auth = authenticate_abl(baseline["abl.img"])
    new_auth = authenticate_abl(target["abl.img"])
    require(old_auth == new_auth, "新版 ABL 的签名元数据、ARB 或证书链变化；禁止恢复旧 ABL")
    release = kernel_release(target["boot.img"])
    boot_header(target["init_boot.img"], init=True)
    require(len(target["init_boot.img"]) == 8388608, "目标 init_boot 必须是完整 8 MiB 镜像")
    plan = dict(schema=1, module_version=VERSION, model="OPD2515", kmi="6.12-android16-6",
                source_build=meta["build"], target_build=build, source_slot=meta["active_slot"], target_slot=meta["target_slot"],
                source_boot_hash=sha(baseline["boot.img"]), source_init_boot_hash=sha(baseline["init_boot.img"]),
                source_abl_hash=sha(baseline["abl.img"]), source_normal_hash=sha(baseline["ABL_normal.efi"]),
                entries_hash=sha(baseline["BOOTENTRIES"]), bds_hash=BDS_HASH, bds_bytes=290816,
                old_abl_hash=OLD_HASH, old_abl_bytes=len(baseline["abl.img"]))
    for name in ("boot", "init_boot", "abl", "xbl", "xbl_config"):
        data = target[name + ".img"]
        cap = int(meta["target_size_" + name])
        require(0 < len(data) <= cap, f"目标镜像超过分区：{name}")
        if name in ("xbl", "xbl_config"):
            data = canonical(data)
            require(data == canonical(baseline[name + ".img"]), f"新版 {name} 的加载段或签名发生变化；本版不支持这次更新")
        plan[name + "_hash"] = sha(data)
        plan[name + "_bytes"] = len(data)
        plan[name + "_capacity"] = cap
    return plan, dict(target_kernel=release, abl_auth=new_auth, xbl_equal=True, xbl_config_equal=True,
                      limitation="Static compatibility checks; real OTA and fuse state are not verified.")


def run_tool(args, log, env=None):
    result = subprocess.run([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    log.write_bytes(result.stdout)
    require(result.returncode == 0, f"工具失败，查看 {log}")
    return result.stdout.decode("utf-8", errors="replace")


def validate_normal_patch_log(log):
    lines = [line.strip() for line in log.splitlines()]
    warnings = [line for line in lines if re.search(r"(?:^|\s)(?:Warning|Error):", line) or line.startswith("Failed")]
    require(all(line == "Warning: Failed to patch ABL GBL" for line in warnings), "Normal Boot 补丁失败或出现未知警告，需人工检查")
    require(any(line.startswith("Patch mode: normal") and "boot state transparent" in line for line in lines), "补丁不是 Normal Boot 模式")
    require(any("warning disabled" in line and line.startswith("Patched CBZ") for line in lines), "没有去除启动警告的成功记录")
    require(any("fastboot always enabled" in line and line.startswith("Patched fastboot") for line in lines), "没有启用 fastboot 的成功记录")


def review_packages(current_path, target_path, base, meta, target_images, target_build):
    current, target = inspect_ota(current_path), inspect_ota(target_path)
    require(current.get("payload_found") and target.get("payload_found"), "需要可解析的当前和目标完整 OTA 包")
    require(current["full_or_delta"] == target["full_or_delta"] == "self_contained", "保留包生成暂不支持源分区依赖的增量 payload")
    for report in (current, target):
        require(report.get("ota_metadata", {}).get("product_name") == "OPD2515", "完整包的 product_name 不符")
        require(report["ota_metadata"].get("ota-type") == "AB", "不是已支持的 A/B 完整包")
    cm = current["ota_metadata"]
    require(meta["build"] in (cm.get("version_name"), cm.get("version_name_show"), cm.get("post-build-incremental")), "当前完整包与运行版本不符")
    require(target_build in (target["ota_metadata"].get("version_name"), target["ota_metadata"].get("version_name_show")), "目标版本与完整包 metadata 不符")
    before = {p["name"]: p for p in current["partitions"]}
    after = {p["name"]: p for p in target["partitions"]}
    require(set(before) == set(after), "固件分区集合变化，需要重新适配和审查")
    require(FIRMWARE_NAMES.issubset(before), "当前包缺少已知底层固件，不能用局部更新包冒充完整包")
    boot_info = before.get("boot", {}).get("new") or {}
    count = boot_info.get("bytes")
    require(count and count <= len(base["boot.img"]) and sha(base["boot.img"][:count]) == boot_info.get("sha256"), "当前原厂 boot 与当前完整包不符")
    for name in ("boot", "init_boot", "abl", "xbl", "xbl_config"):
        info = after.get(name, {}).get("new") or {}; count = info.get("bytes")
        data = target_images[name + ".img"]
        require(count and count <= len(data) and sha(data[:count]) == info.get("sha256"), f"目标 {name} 与完整包 manifest 不符")
    checks = {}
    for name, item in after.items():
        if item["category"] != "firmware_or_other" and name != "xbl_ramdump":
            continue
        require(name in FIRMWARE_NAMES, "未知底层固件分区：" + name)
        new, old = item.get("new") or {}, before[name].get("new") or {}
        require(new.get("bytes") and new.get("sha256") and new == old, f"底层固件 {name} 发生变化；本版拒绝用旧 ABL 配合这次更新")
        checks[name] = new
    require(checks, "完整包缺少底层固件清单")
    return checks, current, target


def build(args):
    base, meta = read_baseline(args.baseline)
    target = {n + ".img": (args.images / (n + ".img")).read_bytes() for n in ("boot", "init_boot", "abl", "xbl", "xbl_config")}
    firmware, current_package, target_package = review_packages(args.current_package, args.target_package, base, meta, target, args.target_build)
    plan, report = make_plan(base, meta, target, args.target_build)
    plan["firmware_policy"] = "unchanged_declared_firmware"
    plan["firmware_names"] = ",".join(sorted(firmware))
    for name, info in sorted(firmware.items()):
        plan[f"fw_{name}_bytes"] = info["bytes"]
        plan[f"fw_{name}_hash"] = info["sha256"]
    require(not args.out.exists(), "输出目录已存在，请换新目录")
    args.out.mkdir(parents=True)
    tool_dir = args.tools
    for name, digest in TOOL_HASHES.items():
        require(sha((tool_dir / name).read_bytes()) == digest, f"KSU 工具摘要不符：{name}")
    import os
    env = os.environ.copy()
    env["PATH"] = str(args.mingw_bin) + os.pathsep + env["PATH"]
    gbl = args.gbl_source
    require(subprocess.check_output([str(args.git), "-C", str(gbl), "rev-parse", "HEAD"]).decode().strip() == "2cf345a299df3f8b7172d6ad2fa5985e67fe53d6", "GBL 源码版本不符")
    extractor = gbl / "submodules/ablfvextractor/build/extractfv.exe"
    patcher = gbl / "submodules/patcher/build/patch_abl.exe"
    # Bind binaries to the release build manifest, rather than trusting PATH.
    manifest = json.loads((PROJECT / "build-manifest.json").read_text(encoding="utf-8"))
    for name, path in (("extractfv", extractor), ("patch_abl", patcher)):
        require(sha(path.read_bytes()) == manifest["review_tool_hashes"][name], f"GBL 工具摘要不符：{name}")
    normal = args.out / "ABL_normal.efi"
    # These MinGW C tools use narrow paths. Use an ASCII working directory and
    # pass the already-checked bytes, so a Chinese workspace path is supported.
    with tempfile.TemporaryDirectory(prefix="opd-ota-review-", dir=args.tool_temp_root) as tmp:
        stage = pathlib.Path(tmp)
        (stage / "abl.img").write_bytes(target["abl.img"])
        extracted = stage / "extracted"
        run_tool([extractor, "-o", extracted, stage / "abl.img"], args.out / "extract.log", env)
        candidates = list(extracted.rglob("*.efi"))
        require(len(candidates) == 1, "提取结果不是唯一 EFI，停止自动处理")
        original_efi = candidates[0].read_bytes()
        log = run_tool([patcher, candidates[0], stage / "ABL_normal.efi", "normal"], args.out / "patch-normal.log", env)
        normal.write_bytes((stage / "ABL_normal.efi").read_bytes())
    validate_normal_patch_log(log)
    validate_pe(normal.read_bytes())
    require(normal.read_bytes() != original_efi, "EFI 补丁未改变镜像")
    patched = args.out / "patched-init_boot.img"
    stock_init = args.out / "stock-init_boot.img"
    stock_init.write_bytes(target["init_boot.img"])
    run_tool([tool_dir / "ksud-x86_64-pc-windows-gnu.exe", "boot-patch", "--boot", stock_init,
              "--module", tool_dir / "lkm-aarch64-android16-6.12_kernelsu.ko", "--init", tool_dir / "ksuinit-aarch64",
              "--kmi", "android16-6.12", "--arch", "aarch64", "--out", args.out, "--out-name", patched.name], args.out / "patch-ksu.log")
    data = patched.read_bytes()
    boot_header(data, init=True)
    require(len(data) == 8388608 and data != target["init_boot.img"], "修补镜像大小异常或未改变")
    (args.out / "old-abl.img").write_bytes(base["abl.img"])
    plan.update(patched_bytes=len(data), patched_hash=sha(data), normal_bytes=normal.stat().st_size, normal_hash=sha(normal.read_bytes()))
    plan_text = "".join(f"{k}={v}\n" for k, v in plan.items())
    require(len(plan_text.encode("utf-8")) <= 12000, "计划超过模块读取上限")
    (args.out / "plan.txt").write_text(plan_text, encoding="utf-8", newline="\n")
    packet = args.out / "OPD2515-OTA-approved.zip"
    with zipfile.ZipFile(packet, "x", compression=zipfile.ZIP_DEFLATED) as zipout:
        for name in ("plan.txt", "patched-init_boot.img", "ABL_normal.efi", "old-abl.img"):
            zipout.write(args.out / name, name)
    digest = sha(packet.read_bytes())
    report.update(source_build=meta["build"], target_build=args.target_build, source_slot=meta["active_slot"], target_slot=meta["target_slot"],
                  packet_sha256=digest, packet=str(packet), static_checks_passed=True, real_device_tested=False,
                  ksu_version="3.3.0", ksu_stock_restore_metadata=False, ota_package_requirement="Official full firmware; incremental OTA unsupported in rc2",
                  declared_firmware_unchanged=list(sorted(firmware)), current_manifest_sha256=current_package["manifest_sha256"],
                  target_manifest_sha256=target_package["manifest_sha256"], ota_package_signatures_verified=False)
    (args.out / "review-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "OPD2515-OTA-approved.zip.sha256").write_text(digest + "\n", encoding="ascii")
    print("静态检查通过。本包仅匹配本次备份和目标固件，不能重复用于另一次升级。")
    print("保留包：", packet)
    print("SHA256：", digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=pathlib.Path, required=True, help="模块升级前导出的 tar.gz")
    parser.add_argument("--images", type=pathlib.Path, required=True, help="目标官方完整固件提取目录")
    parser.add_argument("--target-build", required=True)
    parser.add_argument("--current-package", type=pathlib.Path, required=True, help="当前版本的官方完整 OTA 包")
    parser.add_argument("--target-package", type=pathlib.Path, required=True, help="目标版本的官方完整 OTA 包")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--tools", type=pathlib.Path, default=WORKSPACE / "root-work/tools")
    parser.add_argument("--gbl-source", type=pathlib.Path, default=WORKSPACE / "root-work/gbl-source")
    parser.add_argument("--mingw-bin", type=pathlib.Path, default=pathlib.Path("D:/DevTools/MSYS2/mingw64/bin"))
    parser.add_argument("--git", type=pathlib.Path, default=pathlib.Path("D:/Git/cmd/git.exe"))
    parser.add_argument("--tool-temp-root", type=pathlib.Path, default=pathlib.Path("D:/DevTools/MSYS2/tmp"))
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError, struct.error, KeyError, InvalidSignature, UnsupportedAlgorithm) as error:
        parser.exit(1, "BLOCKED: " + (str(error) or type(error).__name__) + "\n")


if __name__ == "__main__":
    main()
