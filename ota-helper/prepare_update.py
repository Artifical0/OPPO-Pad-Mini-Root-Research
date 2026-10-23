"""Build a per-device, per-update packet on Windows. Never contacts a device."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "OPD2515-OTA-Helper/tools"))
import review as legacy
from extract_selected_payload import extract
from inspect_payload import inspect as inspect_ota
from verify_ota_zip import verify

VERSION = "0.2.0-rc1"
SIGNER = "2de09468859e8f347c52149c319ad83046d6a0e1e11ad89b69ffcf8c35aaac6a"
KSU_DIRS = {
    "ksud 3.3.0 (uapi: 2)": "root-work/tools",
    "ksud 3.3.1 (uapi: 5)": "root-work/ColorOS17-17.0.0.103-analysis/ksu-3.3.1-tools",
}
NAMES = ("boot", "init_boot", "abl", "xbl", "xbl_config")
require = legacy.require
sha = legacy.sha


def validate_menu(data):
    require(len(data) <= 8192 and b"\r" not in data, "菜单必须是 LF 文本")
    lines = data.decode("utf-8").splitlines()
    require(lines[:2] == ["Normal Boot:ABL_normal.efi", "%Android Tools:tools\\ENTRIES"], "默认菜单必须指向 Normal EFI")
    require(all(re.fullmatch(r"\$[^:\r\n]{1,80}:[A-Za-z0-9_-]+\.efi", x) for x in lines[2:]), "附加菜单必须是命名 EFI 入口")


def read_baseline(path):
    names = {*(n + ".img" for n in NAMES), "ABL_normal.efi", "BOOTENTRIES", "device.txt", "SHA256SUMS"}
    blobs = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if name in ("", ".") and member.isdir():
                continue
            require(name in names and name not in blobs and member.isfile(), "备份含异常路径、链接或重复成员")
            limit = 128 * 1024 * 1024 if name.endswith(".img") else 2 * 1024 * 1024
            require(0 < member.size <= limit, "备份成员长度异常")
            blobs[name] = archive.extractfile(member).read(limit + 1)
    require(set(blobs) == names, "备份不完整")
    sums = {}
    for line in blobs["SHA256SUMS"].decode("ascii").splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.strip().removeprefix("*")
        require(name in names - {"SHA256SUMS"} and name not in sums and re.fullmatch("[0-9a-f]{64}", digest), "备份摘要表异常")
        require(sha(blobs[name]) == digest, "备份摘要不符：" + name)
        sums[name] = digest
    require(set(sums) == names - {"SHA256SUMS"}, "备份缺少摘要")
    meta = legacy.read_kv(blobs["device.txt"])
    require(meta.get("schema") == "2" and meta.get("model") == "OPD2515", "请使用 0.2 版模块重新导出备份")
    require(meta.get("ksu_version") in KSU_DIRS, "不支持该 KSU 版本")
    require(meta.get("raw_device_state") == "unlocked" and meta.get("raw_verifiedbootstate") == "orange", "需要真实解锁的 Normal Boot")
    require((meta.get("active_slot"), meta.get("target_slot")) in (("a", "b"), ("b", "a")), "备份槽位异常")
    require(re.fullmatch(r"OPD2515_[0-9A-Za-z_.()-]+", meta.get("build", "")), "运行固件名异常")
    require(sha(blobs["abl.img"]) == legacy.OLD_HASH and meta.get("bds_hash") == legacy.BDS_HASH, "启动链不是已验证组合")
    for name in NAMES:
        require(str(len(blobs[name + ".img"])) == meta.get("size_" + name) == meta.get("target_size_" + name), "A/B 容量不符：" + name)
    require(legacy.kernel_release(blobs["boot.img"]) == meta.get("kernel"), "内核与备份不一致")
    legacy.boot_header(blobs["init_boot.img"], init=True)
    legacy.validate_pe(blobs["ABL_normal.efi"])
    validate_menu(blobs["BOOTENTRIES"])
    return blobs, meta


def verify_official(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and "payload.bin" in names and "META-INF/com/android/metadata" in names, "需要无重复成员的标准完整 OTA")
    result = verify(path)
    require(result.get("whole_file_signature_valid") and result.get("all_entry_crcs_valid"), "完整包签名或 CRC 不符")
    require(result.get("signer_certificate_sha256") == SIGNER, "OTA 签名证书变化，需另行审查")
    return result


def make_plan(base, meta, images, build, current_path, target_path):
    require(re.fullmatch(r"OPD2515_[0-9A-Za-z_.()-]+", build), "目标固件名异常")
    versions = [re.match(r"OPD2515_(\d+)\.(\d+)\.(\d+)\.(\d+)\(", v) for v in (meta["build"], build)]
    require(all(versions), "只支持明确的四段官方版本号")
    require(tuple(map(int, versions[1].groups())) > tuple(map(int, versions[0].groups())), "只支持升级，不支持同版本重刷或降级")
    firmware, current, target = legacy.review_packages(current_path, target_path, base, meta, images, build)
    require(set(firmware) == legacy.FIRMWARE_NAMES, "需要完整的 39 项底层固件清单")
    plan, report = legacy.make_plan(base, meta, images, build)
    plan.update(schema=2, module_version=VERSION, ksu_version=meta["ksu_version"],
                firmware_policy="unchanged_declared_firmware", firmware_names=",".join(sorted(firmware)))
    for name, info in sorted(firmware.items()):
        plan[f"fw_{name}_bytes"] = info["bytes"]
        plan[f"fw_{name}_hash"] = info["sha256"]
    report.update(current_manifest_sha256=current["manifest_sha256"], target_manifest_sha256=target["manifest_sha256"])
    return plan, report


def pinned_tool(relative):
    manifest = json.loads((ROOT / "materials-manifest.json").read_text(encoding="utf-8"))
    record = next(x for x in manifest["files"] if x["path"] == relative)
    path = ROOT / relative
    require(path.stat().st_size == record["bytes"] and sha(path.read_bytes()) == record["sha256"], "工具摘要不符：" + relative)
    return path.resolve()


def patch_images(images, meta, out, runtime_dir=None, temp_root=None):
    require(os.name == "nt", "生成 EFI/KSU 使用已固定摘要的 Windows 工具；请在 Windows 运行")
    gbl = "root-work/gbl-source/submodules/"
    extractor = pinned_tool(gbl + "ablfvextractor/build/extractfv.exe")
    patcher = pinned_tool(gbl + "patcher/build/patch_abl.exe")
    ksu = {n: pinned_tool(KSU_DIRS[meta["ksu_version"]] + "/" + n) for n in (
        "ksud-x86_64-pc-windows-gnu.exe", "ksuinit-aarch64", "lkm-aarch64-android16-6.12_kernelsu.ko")}
    env = os.environ.copy()
    if runtime_dir:
        env["PATH"] = str(runtime_dir) + os.pathsep + env["PATH"]
    with tempfile.TemporaryDirectory(prefix="opd-update-", dir=temp_root) as temp:
        stage = Path(temp)
        require(str(stage).isascii(), "请用 --temp-root 指定可写的纯英文临时目录")
        (stage / "abl.img").write_bytes(images["abl.img"])
        (stage / "init_boot.img").write_bytes(images["init_boot.img"])
        legacy.run_tool([extractor, "-o", stage / "efi", stage / "abl.img"], out / "extract.log", env)
        candidates = list((stage / "efi").rglob("*.efi"))
        require(len(candidates) == 1, "目标 ABL 未提取出唯一 EFI")
        log = legacy.run_tool([patcher, candidates[0], stage / "ABL_normal.efi", "normal"], out / "patch-normal.log", env)
        legacy.validate_normal_patch_log(log)
        normal = (stage / "ABL_normal.efi").read_bytes()
        legacy.validate_pe(normal)
        require(normal != candidates[0].read_bytes(), "Normal 补丁没有改变文件")
        legacy.run_tool([ksu["ksud-x86_64-pc-windows-gnu.exe"], "boot-patch", "--boot", stage / "init_boot.img",
                         "--module", ksu["lkm-aarch64-android16-6.12_kernelsu.ko"], "--init", ksu["ksuinit-aarch64"],
                         "--kmi", "android16-6.12", "--arch", "aarch64", "--out", stage,
                         "--out-name", "patched-init_boot.img"], out / "patch-ksu.log", env)
        patched = (stage / "patched-init_boot.img").read_bytes()
    legacy.boot_header(patched, init=True)
    require(len(patched) == 8388608 and patched != images["init_boot.img"], "KSU 修补结果异常")
    return normal, patched


def write_packet(out, base, plan, normal, patched):
    plan.update(normal_bytes=len(normal), normal_hash=sha(normal), patched_bytes=len(patched), patched_hash=sha(patched))
    text = "".join(f"{k}={v}\n" for k, v in plan.items()).encode("utf-8")
    require(len(text) <= 12000, "计划超过模块限制")
    files = {"plan.txt": text, "ABL_normal.efi": normal, "patched-init_boot.img": patched, "old-abl.img": base["abl.img"]}
    packet = out / "OPD2515-OTA-approved.zip"
    with zipfile.ZipFile(packet, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 23, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    digest = sha(packet.read_bytes())
    (out / "OPD2515-OTA-approved.zip.sha256").write_text(digest + "\n", encoding="ascii", newline="\n")
    return packet, digest


def prepare(args):
    require(not args.out.exists(), "输出目录已存在，请换一个新目录")
    base, meta = read_baseline(args.baseline)
    stamps = [(p.stat().st_size, p.stat().st_mtime_ns) for p in (args.current_package, args.target_package)]
    signatures = [verify_official(p) for p in (args.current_package, args.target_package)]
    target_report = inspect_ota(args.target_package)
    build = target_report.get("ota_metadata", {}).get("version_name")
    require(isinstance(build, str), "完整包缺少 version_name")
    args.out.mkdir(parents=True)
    extracted = args.out / "target-images"
    extract(args.target_package, extracted, list(NAMES))
    images = {n + ".img": (extracted / (n + ".img")).read_bytes() for n in NAMES}
    plan, report = make_plan(base, meta, images, build, args.current_package, args.target_package)
    normal, patched = patch_images(images, meta, args.out, args.runtime_dir, args.temp_root)
    require(stamps == [(p.stat().st_size, p.stat().st_mtime_ns) for p in (args.current_package, args.target_package)], "审查期间固件包发生变化")
    packet, digest = write_packet(args.out, base, plan, normal, patched)
    report.update(source_build=meta["build"], target_build=build, source_slot=meta["active_slot"], target_slot=meta["target_slot"],
                  ksu_version=meta["ksu_version"], packet_sha256=digest, static_checks_passed=True,
                  real_device_tested=False, real_ota_tested=False, ota_signatures=signatures,
                  limitation="Full OTA only; all 39 firmware images, XBL/XBL config and ABL authentication metadata must remain unchanged.")
    (args.out / "review-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"静态检查通过；尚无真机 OTA 验证。\n保留包：{packet}\nSHA256：{digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current-package", type=Path, required=True)
    parser.add_argument("--target-package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, help="Optional MinGW64 DLL directory")
    parser.add_argument("--temp-root", type=Path, help="Writable ASCII-only directory for native tools")
    args = parser.parse_args()
    try:
        prepare(args)
    except Exception as error:
        parser.exit(1, "BLOCKED: " + (str(error) or type(error).__name__) + "\n")
