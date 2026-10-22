"""Read a connected OPD2515 pending update; no phone writes, reboots or setting changes."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

import review

PARTITIONS = ("boot", "init_boot", "abl", "xbl", "xbl_config", "vbmeta", "vendor_boot", "dtbo")


def sha_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect(adb, serial, out):
    def command(args, timeout=30):
        result = subprocess.run([str(adb), "-s", serial, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode("utf-8", "replace").strip()
    def shell(script):
        return command(["shell", "-T", script])
    def su(script):
        return shell("su -c " + shlex.quote(script))
    def identity():
        props = ("ro.product.model", "ro.build.display.id", "ro.build.version.incremental", "ro.build.fingerprint",
                 "ro.boot.slot_suffix", "ro.boot.flash.locked", "ro.boot.verifiedbootstate", "ro.build.version.security_patch")
        return {prop: shell("getprop " + prop) for prop in props}
    before = identity()
    review.require(before["ro.product.model"] == "OPD2515", "设备不是 OPD2515")
    review.require(before["ro.boot.slot_suffix"] in ("_a", "_b"), "无法确认当前槽位")
    review.require(re.search(r"\buid=0\(", su("id")), "Shell 没有 root 授权")
    review.require(not out.exists(), "输出目录已经存在")
    out.mkdir(parents=True)
    report = {"captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "identity": before,
              "phone_read_only": True, "partitions": {}, "all_exports_verified": False,
              "reboot_decision": "NOT_APPROVED", "errors": []}
    try:
        for name, script in {
            "kernel.txt": "uname -r",
            "root.txt": "id; grep '^kernelsu ' /proc/modules; /data/adb/ksud -V",
            "update-engine.txt": "/data/adb/ksu/bin/busybox timeout 4 /system/bin/update_engine_client --follow 2>&1; true",
            "bootctl-readonly.txt": "/data/adb/ksu/bin/bootctl hal-info 2>&1; true",
            "ota-cache-inventory.txt": "for d in /data/ota_package /data/ota /data/misc/update_engine; do if [ -d \"$d\" ]; then /data/adb/ksu/bin/busybox find \"$d\" -maxdepth 2 -type f -exec ls -ln '{}' ';'; fi; done",
            "ksu-stock-backups.txt": "for f in /data/adb/ksu/ksu_backup_*; do [ -f \"$f\" ] && sha256sum \"$f\"; done; true",
        }.items():
            (out / name).write_text(su(script), encoding="utf-8")
        engine = (out / "update-engine.txt").read_text(encoding="utf-8")
        statuses = re.findall(r"onStatusUpdate\((UPDATE_STATUS_[A-Z_]+) \((\d+)\)", engine)
        report["update_engine_status"] = statuses[-1][0] if statuses else "UNKNOWN"
        report["ab_updated_needs_reboot"] = bool(statuses and statuses[-1] == ("UPDATE_STATUS_UPDATED_NEED_REBOOT", "6"))
        # Data travels through exec-out as bytes, never PowerShell text redirection.
        for name in PARTITIONS:
            for slot in ("a", "b"):
                part = f"{name}_{slot}"; remote = "/dev/block/by-name/" + part
                if su(f"if [ -b {remote} ]; then echo YES; else echo NO; fi") != "YES":
                    continue
                size = int(su("blockdev --getsize64 " + remote))
                review.require(0 < size <= 128 * 1024 * 1024, "异常分区容量：" + part)
                expected = su("sha256sum " + remote).split()[0]
                review.require(re.fullmatch(r"[0-9a-f]{64}", expected), "设备摘要异常")
                target = out / (part + ".img")
                print("读取", part, size, "bytes", flush=True)
                with target.open("xb") as output, (out / (part + ".read.log")).open("wb") as errors:
                    # adbd exec-out can merge remote stderr into the byte stream.
                    # Silence dd's counters; exit code, exact size and device hashes
                    # still detect a failed or incomplete read.
                    result = subprocess.run([str(adb), "-s", serial, "exec-out", "su -c " + shlex.quote("dd if=" + remote + " bs=1048576 2>/dev/null")],
                                            stdout=output, stderr=errors, timeout=180)
                review.require(result.returncode == 0 and target.stat().st_size == size, "读取失败：" + part)
                actual = sha_file(target)
                after_hash = su("sha256sum " + remote).split()[0]
                review.require(actual == expected == after_hash, "读取中分区改变或导出损坏：" + part)
                entry = {"bytes": size, "sha256": actual, "verified": True}
                if name in ("abl", "xbl", "xbl_config"):
                    try:
                        data = target.read_bytes()
                        entry["elf_span_sha256"] = review.sha(review.canonical(data))
                        if name == "abl": entry["authentication"] = review.authenticate_abl(data)
                    except Exception as error:
                        entry["inspection_error"] = str(error) or type(error).__name__
                if name == "boot":
                    try: entry["supported_kernel_release"] = review.kernel_release(target.read_bytes())
                    except ValueError as error: entry["kernel_check_error"] = str(error)
                report["partitions"][part] = entry
        after = identity()
        review.require(after == before, "诊断期间设备版本、槽位或状态发生变化")
        after_engine = su("/data/adb/ksu/bin/busybox timeout 4 /system/bin/update_engine_client --follow 2>&1; true")
        (out / "update-engine-after.txt").write_text(after_engine, encoding="utf-8")
        last_statuses = re.findall(r"onStatusUpdate\((UPDATE_STATUS_[A-Z_]+) \((\d+)\)", after_engine)
        review.require(last_statuses == statuses, "诊断期间 OTA 状态改变；这份导出不可直接使用")
        for name in ("xbl", "xbl_config"):
            a, b = report["partitions"].get(name + "_a", {}), report["partitions"].get(name + "_b", {})
            report[name + "_ab_equal"] = bool(a.get("elf_span_sha256") and a.get("elf_span_sha256") == b.get("elf_span_sha256"))
        # A standalone diagnostic can export a baseline without installing a
        # module or taking the dangerous initial-install reboot while OTA is pending.
        baseline = out / "baseline"
        baseline.mkdir()
        for name in ("ABL_normal.efi", "BOOTENTRIES"):
            remote = "/mnt/vendor/persist/efisp/" + name
            size = int(su("stat -c %s " + remote))
            review.require(0 < size <= 2097152, "EFI 文件大小异常")
            expected = su("sha256sum " + remote).split()[0]
            with (baseline / name).open("xb") as stream:
                result = subprocess.run([str(adb), "-s", serial, "exec-out", "su -c " + shlex.quote("cat " + remote)],
                                        stdout=stream, stderr=subprocess.PIPE, timeout=30)
            review.require(result.returncode == 0 and (baseline / name).stat().st_size == size and sha_file(baseline / name) == expected == su("sha256sum " + remote).split()[0], "EFI 导出不符")
        active = before["ro.boot.slot_suffix"][-1]
        target_slot = "b" if active == "a" else "a"
        bds = su("/data/adb/ksu/bin/busybox head -c 290816 /dev/block/by-name/efisp | sha256sum").split()[0]
        meta = dict(schema="1", model="OPD2515", build=before["ro.build.version.incremental"],
                    kernel=(out / "kernel.txt").read_text(), active_slot=active, target_slot=target_slot, bds_hash=bds)
        for name in ("boot", "init_boot", "abl", "xbl", "xbl_config"):
            source = out / f"{name}_{active}.img"
            shutil.copyfile(source, baseline / (name + ".img"))
            meta["size_" + name] = str(report["partitions"][f"{name}_{active}"]["bytes"])
            meta["target_size_" + name] = str(report["partitions"][f"{name}_{target_slot}"]["bytes"])
        (baseline / "device.txt").write_text("".join(f"{k}={v}\n" for k, v in meta.items()), encoding="utf-8", newline="\n")
        (baseline / "SHA256SUMS").write_text("".join(f"{sha_file(p)}  {p.name}\n" for p in sorted(baseline.iterdir())), encoding="ascii")
        report["baseline_directory"] = str(baseline)
        review.require(identity() == before, "基线导出期间设备状态改变")
        report["all_exports_verified"] = True
    except Exception as error:
        report["errors"].append(str(error) or type(error).__name__)
        raise
    finally:
        (out / "pending-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("只读诊断完成。尚未批准重启，也没有执行任何保留写入。", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=pathlib.Path, default=pathlib.Path("adb"))
    parser.add_argument("--serial", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try: collect(args.adb, args.serial, args.out)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, "诊断停止：" + str(error) + "\n")


if __name__ == "__main__":
    main()
