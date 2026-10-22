"""Device-specific 17.0.0.103 preparation/check/transaction. Never reboots or sets a slot."""
import argparse
import os
import datetime
import hashlib
import json
import pathlib
import re
import shlex
import struct
import subprocess

import review

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADB = pathlib.Path(os.environ.get("OPD_ADB", "adb"))
SERIAL = os.environ.get("OPD_SERIAL", "")
HAL = "android.hardware.boot.IBootControl/default"
HAL_HASH = "2400346954240a5de495a1debc81429dd012d7b7"
PACKAGE_HASH = "aeeb3029c64f3a7251bf861325a21388c1817739c8684155ba7daa71f6beb8d5"
PATCH_HASH = "ddd0e19a562a33040f99282e23db848b4371d66b88581952843be33bfd516fc3"
NORMAL_HASH = "2efe7efced64c4caaea203277245e16ff0523e800a82ff87cc44642f8b3f4170"
SOURCE_NORMAL_HASH = "6fa5baed02ca05743491afe32e30470f1ec1afb0cca94fe1cd6dbd560242e503"
EFI = "/mnt/vendor/persist/efisp"
RAW_NAMES = {"boot", "init_boot", "abl", "xbl", "xbl_config", "vbmeta", "vendor_boot", "dtbo"}
TARGET_NAMES = RAW_NAMES | review.FIRMWARE_NAMES
NEW_MENU = ("Normal Boot:ABL_normal.efi\n%Android Tools:tools\\ENTRIES\n"
            "$500 EFI - only with verified 500 slot:ABL_500.efi\n"
            "$17 EFI:ABL_17.efi\n")


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def parcel(text):
    if "0x00000000:" not in text:
        words = re.findall(r"\b[0-9a-f]{8}\b", text.split("'")[0].lower())
    else:
        words = []
        for line in text.lower().splitlines():
            if re.match(r"^0x[0-9a-f]+:", line):
                words += re.findall(r"\b[0-9a-f]{8}\b", line.split(":", 1)[1].split("'")[0])
    require(len(words) >= 2 and words[0] == "00000000", "HAL exception or invalid parcel")
    return bytes().join(struct.pack("<I", int(x, 16)) for x in words[1:])


class Device:
    def shell(self, cmd, timeout=120):
        require(bool(SERIAL), "Set OPD_SERIAL explicitly before contacting a device")
        r = subprocess.run([str(ADB), "-s", SERIAL, "exec-out", "su -c " + shlex.quote(cmd)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        require(r.returncode == 0, r.stderr.decode("utf-8", "replace") + r.stdout[:2048].decode("utf-8", "replace"))
        return r.stdout.decode("utf-8", "replace").strip()

    def call(self, code, slot=None):
        require(code in (1, 2, 3, 4, 6, 7, 16777214, 16777215), "Mutating HAL call forbidden")
        require(slot is None or (code in (6, 7) and slot in (0, 1)), "Invalid HAL argument")
        result = self.shell(f"service call {HAL} {code}" + (f" i32 {slot}" if slot is not None else ""))
        data = parcel(result)
        if code == 16777214:
            length = struct.unpack_from("<I", data)[0]
            return data[4:4+length*2].decode("utf-16-le")
        require(len(data) == 4, "Invalid integer parcel")
        return struct.unpack("<I", data)[0]

    def state(self):
        require(self.call(16777215) == 1 and self.call(16777214) == HAL_HASH, "Unreviewed HAL interface")
        props = ("ro.product.model", "ro.build.display.id", "ro.boot.slot_suffix")
        state = {p: self.shell("getprop " + p) for p in props}
        state["uid"] = self.shell("id -u")
        state["ksu"] = self.shell("/data/adb/ksud -V")
        state["kernel"] = self.shell("uname -r")
        state["bootconfig"] = self.shell("cat /proc/bootconfig")
        state["lkm_live"] = bool(re.search(r"^kernelsu .* Live ", self.shell("cat /proc/modules"), re.M))
        state["current"] = self.call(2)
        state["next"] = self.call(1)
        state["slots"] = self.call(3)
        state["merge"] = self.call(4)
        state["next_bootable"] = bool(self.call(6, state["next"]))
        raw = self.shell("/data/adb/ksu/bin/busybox timeout 4 /system/bin/update_engine_client --follow 2>&1; true")
        states = re.findall(r"onStatusUpdate\((UPDATE_STATUS_[A-Z_]+) \((\d+)\)", raw)
        require(bool(states), "Unknown update engine status")
        state["engine"] = states[-1][0]
        state["enabled_modules"] = self.shell(
            'for d in /data/adb/modules/*; do if [ -f "$d/module.prop" ] && [ ! -e "$d/disable" ] '
            '&& [ ! -e "$d/remove" ]; then basename "$d"; fi; done')
        state["queued_modules"] = self.shell(
            'for d in /data/adb/modules_update/*; do if [ -f "$d/module.prop" ]; then basename "$d"; fi; done')
        return state

    def hash(self, path, length=None):
        cmd = ("sha256sum " + shlex.quote(path) if length is None else
               f"/data/adb/ksu/bin/busybox head -c {int(length)} {shlex.quote(path)} | sha256sum")
        result = self.shell(cmd).split()[0]
        require(re.fullmatch("[0-9a-f]{64}", result), "Invalid digest")
        return result

    def export(self, remote, local, expected, size):
        require(self.hash(remote) == expected, "Backup source changed")
        with local.open("xb") as f:
            r = subprocess.run([str(ADB), "-s", SERIAL, "exec-out", "su -c " + shlex.quote("cat " + remote)],
                               stdout=f, stderr=subprocess.PIPE, timeout=120)
        require(r.returncode == 0 and local.stat().st_size == size and sha(local) == expected ==
                self.hash(remote), "Backup export invalid")


def guard_state(s, pending):
    require(s["ro.product.model"] == "OPD2515" and s["ro.build.display.id"] == "OPD2515_16.0.10.500(CN01)", "Source model/build changed")
    require(s["ro.boot.slot_suffix"] == "_b" and s["current"] == 1 and s["slots"] == 2, "Source slot changed")
    require(s["uid"] == "0" and s["ksu"] == "ksud 3.3.1 (uapi: 5)" and s["lkm_live"], "Root/KSU changed")
    require(s["kernel"] == "6.12.58-android16-6-g7704a1ae279b-ab15213644-4k", "Source kernel changed")
    for k,v in (("vbmeta.device_state", "unlocked"), ("verifiedbootstate", "orange"), ("slot_suffix", "_b")):
        require(re.search(r'androidboot\.'+re.escape(k)+r'\s*=\s*"'+re.escape(v)+r'"', s["bootconfig"]), "Raw boot state changed")
    require(not s["enabled_modules"] and not s["queued_modules"], "Third-party modules not paused or update queued")
    if pending:
        require(s["engine"] == "UPDATE_STATUS_UPDATED_NEED_REBOOT" and s["next"] == 0 and
                s["next_bootable"] and s["merge"] in (0, 2), "OTA not ready for reviewed target a")
    else:
        require(s["engine"] == "UPDATE_STATUS_IDLE" and s["next"] == 1 and s["next_bootable"] and
                s["merge"] == 0, "Source not idle/current b")


def load_plan(path):
    p = json.loads(path.read_text(encoding="utf-8"))
    require(p["schema"] == "OPD2515-17.0.0.103-exact-v1" and p["source_slot"] == "b" and
            p["target_slot"] == "a" and p["package_sha256"] == PACKAGE_HASH, "Unsupported plan")
    require(set(p["target_images"]) == TARGET_NAMES, "Incomplete or unknown target partitions")
    require(set(p["source_partitions"]) == RAW_NAMES and
            set(p["source_firmware"]) == review.FIRMWARE_NAMES | {"xbl", "xbl_config"}, "Incomplete source evidence")
    require(set(p["assets"]) == {"patched","normal","old_abl","source_normal","source_entries","entries"},
            "Incomplete or unknown assets")
    for m in p["target_images"].values():
        require(isinstance(m["bytes"],int) and 0 < m["bytes"] <= 512*1024*1024 and
                re.fullmatch("[0-9a-f]{64}",m["sha256"]), "Invalid target declaration")
    target_report = ROOT/"evidence/17-103/payload-report.json"
    require(sha(target_report) == p["target_report_sha256"], "Reviewed target report changed")
    declared = json.loads(target_report.read_text(encoding="utf-8"))
    require(p["target_images"] == {x["name"]:x["new"] for x in declared["partitions"] if x["name"] in TARGET_NAMES},
            "Target declaration changed")
    require(p["source_partitions"]["boot"]["sha256"] == "5fd79d25971d171eb18740d37a6fcda56a289bcc4470c642964c988c8b025e72" and
            p["source_partitions"]["init_boot"]["sha256"] == "ca81b0067110ca3cff09b19c9ca15eed46172d4b5adfc5c8db25d79ddb34666f" and
            p["source_partitions"]["abl"]["sha256"] == review.OLD_HASH, "Unsupported source image")
    expected = {"patched":PATCH_HASH, "normal":NORMAL_HASH, "old_abl":review.OLD_HASH,
                "source_normal":SOURCE_NORMAL_HASH}
    for key,m in p["assets"].items():
        f = (ROOT / m["path"]).resolve()
        require(f.is_relative_to(ROOT.resolve()) and not (ROOT / m["path"]).is_symlink(), "Asset path outside workspace")
        require(f.stat().st_size == m["bytes"] and sha(f) == m["sha256"], "Asset changed: " + key)
        m["path"] = str(f)
        if key in expected:
            require(m["sha256"] == expected[key], "Unreviewed asset: " + key)
    require(p["assets"]["patched"]["bytes"] == 8388608 and p["assets"]["old_abl"]["bytes"] == 1048576, "Partial raw image")
    require(pathlib.Path(p["assets"]["entries"]["path"]).read_text(encoding="utf-8") == NEW_MENU, "Menu changed")
    return p


def inspect(d, p, pending):
    before = d.state()
    guard_state(before, pending)
    for name,m in p["source_partitions"].items():
        path = f"/dev/block/by-name/{name}_b"
        require(d.shell("readlink -f " + path) == m["device"], "Source partition alias changed")
        require(int(d.shell("blockdev --getsize64 " + path)) == m["bytes"] and
                d.hash(path) == m["sha256"], "Source image changed: " + name)
    for name,m in p["source_firmware"].items():
        require(d.hash(f"/dev/block/by-name/{name}_b", m["prefix_bytes"]) == m["sha256"],
                "Source firmware changed: " + name)
    require(d.hash(EFI+"/ABL_normal.efi") == SOURCE_NORMAL_HASH and
            d.hash(EFI+"/BOOTENTRIES") == p["assets"]["source_entries"]["sha256"] and
            d.hash("/dev/block/by-name/efisp", 290816) == review.BDS_HASH, "GBL/EFI baseline changed")
    for name,m in p["target_images"].items():
        path = f"/dev/block/by-name/{name}_a"
        require(int(d.shell("blockdev --getsize64 " + path)) >= m["bytes"], "Target capacity invalid")
        if pending:
            require(d.hash(path,m["bytes"]) == m["sha256"], "Target OTA image not reviewed: " + name)
    for name in ("init_boot", "abl"):
        path = f"/dev/block/by-name/{name}_a"
        require(d.shell("readlink -f " + path) == p["target_topology"][name]["device"], "Target alias changed")
        require(int(d.shell("blockdev --getsize64 " + path)) == p["target_topology"][name]["bytes"], "Target raw capacity changed")
    for name,key in (("ABL_500.efi","source_normal"), ("ABL_17.efi","normal")):
        exists = d.shell("if [ -e "+EFI+"/"+name+" ]; then echo YES; else echo NO; fi")
        if exists == "YES":
            require(d.hash(EFI+"/"+name) == p["assets"][key]["sha256"], "Existing EFI conflicts: " + name)
    after = d.state()
    require(after == before, "Live state changed during inspection")
    return before


def build(baseline, out):
    b = json.loads((baseline/"live-report.json").read_text(encoding="utf-8"))
    require(b["capture_complete"] and not b["errors"] and b["active_slot"] == "b", "Incomplete source baseline")
    require(all(m["same_as_latest_record"] and m["existing_backup_verified"] for m in b["partition_hashes"].values()),
            "Source differs from verified backups")
    analysis = ROOT/"root-work/ColorOS17-17.0.0.103-analysis"
    manifest = json.loads((ROOT/"evidence/17-103/payload-report.json").read_text(encoding="utf-8"))
    require(manifest["ota_metadata"]["version_name"] == "OPD2515_17.0.0.103(CN01)" and
            manifest["full_or_delta"] == "self_contained", "Wrong target")
    out.mkdir(exist_ok=True)
    (out/"BOOTENTRIES-17.txt").write_text(NEW_MENU,encoding="utf-8",newline="\n")
    paths = {
        "patched":analysis/"candidates-offline/KSU-3.3.1-init_boot-17.img",
        "normal":analysis/"candidates-offline/ABL_normal-17.efi",
        "old_abl":ROOT/"root-work/coolapk-original/oppo_pad_mini_root_file/abl_a.img",
        "source_normal":baseline/"efi-readonly-backup/ABL_normal.efi",
        "source_entries":baseline/"efi-readonly-backup/BOOTENTRIES",
        "entries":out/"BOOTENTRIES-17.txt"}
    p = {"schema":"OPD2515-17.0.0.103-exact-v1","package_sha256":PACKAGE_HASH,
         "target_report_sha256":sha(ROOT/"evidence/17-103/payload-report.json"),
         "source_slot":"b","target_slot":"a","experimental_new_xbl_old_abl_runtime_verified":False,
         "apply_scope":["init_boot_a","abl_a","persist EFI files and BOOTENTRIES"],
         "never_performs":["OTA install","slot switch","reboot","wipe","unlock/lock","ARB mutation"],
         "rollback_scope":"Only this transaction's init_boot/ABL/EFI changes; not OTA/firmware/data downgrade",
         "source_partitions":{n:b["partition_hashes"][n+"_b"] for n in RAW_NAMES},
         "source_firmware":b["firmware_comparison"],
         "target_topology":{n:b["partition_hashes"][n+"_a"] for n in ("init_boot","abl")},
         "target_images":{x["name"]:x["new"] for x in manifest["partitions"] if x["name"] in TARGET_NAMES},
         "assets":{k:{"path":str(v),"bytes":v.stat().st_size,"sha256":sha(v)} for k,v in paths.items()}}
    path = out/"prepare-plan.json"
    require(not path.exists(), "Plan already exists")
    path.write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    load_plan(path)
    return path


def shell_transaction(p, tx, hashes):
    require(re.fullmatch(r"/data/adb/opd2515_17_103/tx-[0-9_]+", tx), "Invalid transaction path")
    q = shlex.quote
    script = ["#!/system/bin/sh", "set -eu", "umask 077", "BB=/data/adb/ksu/bin/busybox",
              "EFI="+q(EFI), "TX="+q(tx), "DIRTY=0",
              'opd_sha256() { "$BB" sha256sum "$1" | "$BB" awk \'{print $1}\'; }',
              'eqhash() { [ "$(opd_sha256 "$1")" = "$2" ]; }',
              'write_raw() { [ -b "$2" ] || return 1; [ "$("$BB" stat -c %s "$1")" = "$(blockdev --getsize64 "$2")" ] || return 1; blockdev --setrw "$2" || return 1; "$BB" dd if="$1" of="$2" bs=1048576 conv=fsync || return 1; eqhash "$2" "$(opd_sha256 "$1")"; }',
              'atomic() { [ ! -L "$2" ] || return 1; [ ! -e "$2.opd103-tmp" ] || return 1; cp "$1" "$2.opd103-tmp" || return 1; chmod 0644 "$2.opd103-tmp" || return 1; eqhash "$2.opd103-tmp" "$(opd_sha256 "$1")" || return 1; mv "$2.opd103-tmp" "$2" || return 1; sync; eqhash "$2" "$(opd_sha256 "$1")"; }',
              'minimal_guard() {',
              '[ "$(id -u)" = 0 ] || return 1; [ "$(getprop ro.product.model)" = OPD2515 ] || return 1;',
              '[ "$(getprop ro.build.display.id)" = "OPD2515_16.0.10.500(CN01)" ] || return 1; [ "$(getprop ro.boot.slot_suffix)" = _b ] || return 1;',
              f"service call {HAL} 2 | \"$BB\" grep -Eq 'Parcel\\([[:space:]]*00000000[[:space:]]+00000001' || return 1;",
              f"service call {HAL} 1 | \"$BB\" grep -Eq 'Parcel\\([[:space:]]*00000000[[:space:]]+00000000' || return 1;",
              'UE=$("$BB" timeout 4 /system/bin/update_engine_client --follow 2>&1 || true);',
              'echo "$UE" | "$BB" grep "onStatusUpdate(" | "$BB" tail -n 1 | "$BB" grep -q "onStatusUpdate(UPDATE_STATUS_UPDATED_NEED_REBOOT (6),";',
              '}', 'finish() { rc=$?; trap - EXIT HUP INT TERM; if [ "$DIRTY" = 1 ]; then',
              'set +e; if minimal_guard; then',
              'for f in ABL_500.efi ABL_17.efi ABL_normal.efi BOOTENTRIES; do if [ -f "$EFI/$f.opd103-tmp" ] && [ ! -L "$EFI/$f.opd103-tmp" ]; then rm -f "$EFI/$f.opd103-tmp"; fi; done;',
              'if write_raw "$TX/before-init_boot.img" /dev/block/by-name/init_boot_a && write_raw "$TX/before-abl.img" /dev/block/by-name/abl_a && atomic "$TX/before-normal.efi" "$EFI/ABL_normal.efi" && atomic "$TX/before-entries" "$EFI/BOOTENTRIES"; then echo RESTORED_BEFORE_TRANSACTION > "$TX/result"; else echo RESTORE_FAILED > "$TX/result"; fi;',
              'else echo STATE_CHANGED_DO_NOT_REBOOT > "$TX/result"; fi; fi; sync; exit "$rc"; }',
              'trap finish EXIT; trap \'exit 130\' HUP INT TERM', 'minimal_guard']
    for filename,digest in hashes.items():
        script.append("eqhash "+q(tx+"/"+filename)+" "+q(digest))
    for n in ("boot","init_boot","abl"):
        script.append("eqhash /dev/block/by-name/"+n+"_b "+q(p["source_partitions"][n]["sha256"]))
    for n in ("init_boot","abl"):
        script.append("eqhash /dev/block/by-name/"+n+"_a "+q(hashes["before-"+n+".img"]))
    script += ['eqhash "$EFI/ABL_normal.efi" '+q(SOURCE_NORMAL_HASH),
               'eqhash "$EFI/BOOTENTRIES" '+q(p["assets"]["source_entries"]["sha256"]),
               'for f in ABL_500.efi ABL_17.efi ABL_normal.efi BOOTENTRIES; do [ ! -e "$EFI/$f.opd103-tmp" ]; done;',
               'echo READY > "$TX/result"; sync;',
               'DIRTY=1;',
               'atomic "$TX/source_normal" "$EFI/ABL_500.efi";',
               'atomic "$TX/normal" "$EFI/ABL_17.efi";',
               'write_raw "$TX/patched" /dev/block/by-name/init_boot_a;',
               'write_raw "$TX/old_abl" /dev/block/by-name/abl_a;',
               'atomic "$TX/normal" "$EFI/ABL_normal.efi";',
               'atomic "$TX/entries" "$EFI/BOOTENTRIES";',
               'minimal_guard;', 'echo APPLIED > "$TX/result"; sync;', 'DIRTY=0;',
               'echo APPLIED_NO_REBOOT_NO_SLOT_CHANGE']
    return "\n".join(script)+"\n"


def apply(d, p, directory, ack):
    require(ack == "APPLY_OPD2515_17.0.0.103_SLOT_a", "Exact transaction acknowledgment missing")
    inspect(d,p,True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = directory/("transaction-"+now)
    backup.mkdir()
    hashes = {}
    for n in ("init_boot","abl"):
        remote = "/dev/block/by-name/"+n+"_a"
        digest = d.hash(remote)
        local = backup/("before-"+n+".img")
        d.export(remote,local,digest,p["target_topology"][n]["bytes"])
        hashes[local.name] = digest
    for n,f in (("ABL_normal.efi","before-normal.efi"),("BOOTENTRIES","before-entries")):
        remote = EFI+"/"+n
        digest = d.hash(remote)
        d.export(remote,backup/f,digest,int(d.shell("stat -c %s "+remote)))
        hashes[f] = digest
    inspect(d,p,True)
    tx = "/data/adb/opd2515_17_103/tx-"+now
    d.shell("[ ! -L /data/adb/opd2515_17_103 ] && mkdir -p /data/adb/opd2515_17_103 && chmod 0700 /data/adb/opd2515_17_103 && mkdir "+tx)
    staged = {f:backup/f for f in hashes}
    for k,m in p["assets"].items():
        staged[k] = pathlib.Path(m["path"])
        hashes[k] = m["sha256"]
    script = shell_transaction(p,tx,hashes)
    (backup/"apply-device.sh").write_text(script,encoding="utf-8",newline="\n")
    # Upload to shell-owned temporary storage, then copy into the private root directory.
    temp = "/data/local/tmp/opd103-"+now
    r = subprocess.run([str(ADB),"-s",SERIAL,"shell","-T","umask 077; mkdir "+temp],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    require(r.returncode == 0,"Shell-owned upload directory creation failed")
    for name,f in {**staged,"apply-device.sh":backup/"apply-device.sh"}.items():
        r = subprocess.run([str(ADB),"-s",SERIAL,"push",str(f),temp+"/"+name],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        require(r.returncode == 0, "Stage upload failed")
        d.shell("cp "+temp+"/"+name+" "+tx+"/"+name+" && chmod 0600 "+tx+"/"+name)
        require(d.hash(tx+"/"+name) == sha(f), "Private staged asset changed")
    inspect(d,p,True)
    (backup/"transaction.json").write_text(json.dumps({"device_directory":tx,"files":hashes,"scope":p["apply_scope"]},indent=2)+"\n",encoding="utf-8")
    output = d.shell("/system/bin/sh "+tx+"/apply-device.sh",timeout=180)
    (backup/"apply-output.txt").write_text(output,encoding="utf-8")
    require("APPLIED_NO_REBOOT_NO_SLOT_CHANGE" in output, "Apply incomplete; do not reboot")
    require(d.hash("/dev/block/by-name/init_boot_a") == PATCH_HASH and
            d.hash("/dev/block/by-name/abl_a") == review.OLD_HASH and
            d.hash(EFI+"/ABL_normal.efi") == NORMAL_HASH and
            d.hash(EFI+"/BOOTENTRIES") == p["assets"]["entries"]["sha256"], "Post-apply readback invalid")
    require(d.hash(EFI+"/ABL_500.efi") == SOURCE_NORMAL_HASH and
            d.hash(EFI+"/ABL_17.efi") == NORMAL_HASH and
            d.hash("/dev/block/by-name/efisp",290816) == review.BDS_HASH, "EFI recovery material changed")
    for name,m in p["source_partitions"].items():
        require(d.hash("/dev/block/by-name/"+name+"_b") == m["sha256"], "Source partition changed after transaction")
    guard_state(d.state(),True)
    print("APPLIED_AND_READBACK_PASS. Device remains in 500. Do not reboot until boot plan is reviewed.")


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("action",choices=("build","check","apply"))
    a.add_argument("--baseline",type=pathlib.Path)
    a.add_argument("--out",type=pathlib.Path)
    a.add_argument("--plan",type=pathlib.Path)
    a.add_argument("--ack")
    args = a.parse_args()
    if args.action == "build":
        require(args.baseline is not None and args.out is not None,"baseline/out required")
        print(json.dumps({"plan":str(build(args.baseline,args.out))},ensure_ascii=True)); return
    require(args.plan is not None,"plan required")
    p = load_plan(args.plan)
    d = Device()
    if args.action == "check":
        s = d.state()
        pending = s["engine"] == "UPDATE_STATUS_UPDATED_NEED_REBOOT"
        s = inspect(d,p,pending)
        result = {"state":s,"pending":pending,"device_read_only":True,
                  "decision":"READY_FOR_REVIEWED_PRESERVATION" if pending else "READY_FOR_OFFICIAL_INSTALL_NOT_READY_TO_FLASH"}
        (args.plan.parent/"latest-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"decision":result["decision"],"pending":pending,"read_only":True},ensure_ascii=True))
    else:
        apply(d,p,args.plan.parent,args.ack)


if __name__ == "__main__":
    main()
