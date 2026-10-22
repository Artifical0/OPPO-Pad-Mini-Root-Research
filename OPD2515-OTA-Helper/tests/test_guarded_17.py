"""Safety gates only. These tests never contact a device."""
import copy
import shutil
import os
import json
import pathlib
import re
import shlex
import subprocess
import tempfile
import sys
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"tools"))
import guarded_17 as g

PLAN = g.ROOT/"evidence/17-103/prepare-plan.json"


def shell_executable():
    configured = os.environ.get("OPD_BASH")
    if configured: return configured
    git = shutil.which("git")
    candidate = pathlib.Path(git).resolve().parents[1] / "bin/bash.exe" if git else None
    if candidate and candidate.is_file(): return str(candidate)
    if os.name != "nt": return shutil.which("bash")
    raise unittest.SkipTest("Git Bash is required for Windows shell regression checks")



def state(pending=True):
    return {"ro.product.model":"OPD2515","ro.build.display.id":"OPD2515_16.0.10.500(CN01)",
            "ro.boot.slot_suffix":"_b","uid":"0","ksu":"ksud 3.3.1 (uapi: 5)",
            "kernel":"6.12.58-android16-6-g7704a1ae279b-ab15213644-4k","lkm_live":True,
            "bootconfig":'androidboot.vbmeta.device_state = "unlocked"\nandroidboot.verifiedbootstate = "orange"\nandroidboot.slot_suffix = "_b"',
            "current":1,"slots":2,"next":0 if pending else 1,"next_bootable":True,
            "merge":2 if pending else 0,"engine":"UPDATE_STATUS_UPDATED_NEED_REBOOT" if pending else "UPDATE_STATUS_IDLE",
            "enabled_modules":"","queued_modules":""}


class Fake:
    def __init__(self,p):
        self.p=p
        self.s=state()
        self.bad_hash_path=None
        self.bad_alias=None
        self.state_calls=0
        self.change_state=False
        self.exports=[]

    def state(self):
        self.state_calls+=1
        s=copy.deepcopy(self.s)
        if self.change_state and self.state_calls>1: s["next"]=1
        return s

    def shell(self,cmd,timeout=120):
        if cmd.startswith("readlink -f "):
            n=cmd.split("/")[-1]
            name,slot=n.rsplit("_",1)
            if n==self.bad_alias: return self.p["source_partitions"]["init_boot"]["device"]
            return (self.p["source_partitions"][name] if slot=="b" else self.p["target_topology"][name])["device"]
        if cmd.startswith("blockdev --getsize64 "):
            n=cmd.split("/")[-1]
            name,slot=n.rsplit("_",1)
            if slot=="b": return str(self.p["source_partitions"][name]["bytes"])
            if name in self.p["target_topology"]: return str(self.p["target_topology"][name]["bytes"])
            return str(self.p["target_images"][name]["bytes"])
        if cmd.startswith("if [ -e "): return "NO"
        raise AssertionError("Unexpected command, including mutations: "+cmd)

    def hash(self,path,length=None):
        if path==self.bad_hash_path: return "0"*64
        if path==g.EFI+"/ABL_normal.efi": return g.SOURCE_NORMAL_HASH
        if path==g.EFI+"/BOOTENTRIES": return self.p["assets"]["source_entries"]["sha256"]
        if path=="/dev/block/by-name/efisp": return g.review.BDS_HASH
        name,slot=path.split("/")[-1].rsplit("_",1)
        if slot=="a": return self.p["target_images"][name]["sha256"]
        if length is None: return self.p["source_partitions"][name]["sha256"]
        return self.p["source_firmware"][name]["sha256"]

    def export(self,*args):
        self.exports.append(args)
        raise AssertionError("Unsafe gate allowed export/staging")


class Safety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=g.load_plan(PLAN)

    def test_ready_pending(self):
        g.inspect(Fake(self.p),self.p,True)

    def test_idle_preparation_does_not_allow_apply(self):
        f=Fake(self.p);f.s=state(False)
        g.inspect(f,self.p,False)
        with self.assertRaises(ValueError): g.apply(f,self.p,PLAN.parent,"APPLY_OPD2515_17.0.0.103_SLOT_a")
        self.assertEqual(f.exports,[])

    def test_reject_invalid_live_states_before_export(self):
        changes=[("ro.product.model","OTHER"),("ro.build.display.id","OPD2515_17.0.0.103(CN01)"),
                 ("ro.boot.slot_suffix","_a"),("current",0),("next",1),("slots",1),
                 ("uid","2000"),("ksu","ksud 3.3.0 (uapi: 2)"),("lkm_live",False),
                 ("kernel","6.1-other"),("merge",3),("merge",1),("merge",4),
                 ("next_bootable",False),("engine","UPDATE_STATUS_DOWNLOADING"),
                 ("enabled_modules","zygisksu"),("queued_modules","unknown")]
        for k,v in changes:
            with self.subTest(k=k,v=v):
                f=Fake(self.p);f.s[k]=v
                with self.assertRaises(ValueError): g.apply(f,self.p,PLAN.parent,"APPLY_OPD2515_17.0.0.103_SLOT_a")
                self.assertEqual(f.exports,[])

    def test_raw_boot_state_not_spoofed_properties(self):
        s=state();s["ro.boot.flash.locked"]="1";s["ro.boot.verifiedbootstate"]="green"
        g.guard_state(s,True)
        s["bootconfig"]=s["bootconfig"].replace('"unlocked"','"locked"')
        with self.assertRaises(ValueError): g.guard_state(s,True)

    def test_target_and_source_hash_mismatch_reject_before_export(self):
        for path in ("/dev/block/by-name/init_boot_a","/dev/block/by-name/xbl_a",
                     "/dev/block/by-name/keymaster_a","/dev/block/by-name/boot_b",
                     "/dev/block/by-name/tz_b",g.EFI+"/BOOTENTRIES"):
            with self.subTest(path=path):
                f=Fake(self.p);f.bad_hash_path=path
                with self.assertRaises(ValueError): g.apply(f,self.p,PLAN.parent,"APPLY_OPD2515_17.0.0.103_SLOT_a")
                self.assertEqual(f.exports,[])

    def test_alias_to_active_partition_rejected(self):
        f=Fake(self.p);f.bad_alias="init_boot_a"
        with self.assertRaises(ValueError): g.inspect(f,self.p,True)

    def test_state_race_rejected(self):
        f=Fake(self.p);f.change_state=True
        with self.assertRaises(ValueError): g.inspect(f,self.p,True)

    def test_wrong_ack_rejected(self):
        f=Fake(self.p)
        with self.assertRaises(ValueError): g.apply(f,self.p,PLAN.parent,"APPLY_b")
        self.assertEqual(f.state_calls,0)

    def test_read_only_hal_allowlist(self):
        d=g.Device()
        for c in (8,9,10,11,0):
            with self.subTest(code=c),self.assertRaises(ValueError): d.call(c)

    def test_parcel_rejects_exception(self):
        with self.assertRaises(ValueError): g.parcel("Result: Parcel(fffffffe 00000000)")
        self.assertEqual(g.parcel("Result: Parcel(00000000 00000001 '........')"),b"\x01\x00\x00\x00")

    def test_transaction_has_no_reboot_or_hal_setters(self):
        h={n:"a"*64 for n in ("before-init_boot.img","before-abl.img","before-normal.efi","before-entries")}
        text=g.shell_transaction(self.p,"/data/adb/opd2515_17_103/tx-20261014_000000",h)
        for forbidden in ("adb reboot","fastboot","set-active-boot-slot","mark-boot-successful","reboot -",
                          "flashing lock","setSnapshotMergeStatus"):
            self.assertNotIn(forbidden,text)
        self.assertIn("RESTORED_BEFORE_TRANSACTION",text)
        self.assertIn("STATE_CHANGED_DO_NOT_REBOOT",text)
        self.assertIn("conv=fsync",text)
        self.assertNotIn("of=/dev/block/by-name/init_boot_b",text)

    def test_transaction_hal_guard_accepts_device_whitespace_and_rejects_wrong_slots(self):
        h={n:"a"*64 for n in ("before-init_boot.img","before-abl.img","before-normal.efi","before-entries")}
        script=g.shell_transaction(self.p,"/data/adb/opd2515_17_103/tx-20261014_000000",h)
        patterns=re.findall(r"grep -Eq '([^']+)'",script)
        self.assertEqual(len(patterns),2)
        bash=shell_executable()
        if not bash: self.skipTest('bash is required for shell regression checks')
        for pattern,good,bad in ((patterns[0],'00000001','00000000'),(patterns[1],'00000000','00000001')):
            for gap in ('',' ','\t','\t  '):
                for value,exception,expected in ((good,'00000000',0),(bad,'00000000',1),(good,'fffffffe',1)):
                    parcel="Result: Parcel("+gap+exception+" "+value+"   '........')"
                    command='printf "%s\\n" "$1" | grep -Eq '+shlex.quote(pattern)
                    result=subprocess.run([str(bash),'-c',command,'--',parcel],capture_output=True)
                    with self.subTest(gap=gap,value=value,exception=exception):
                        self.assertEqual(result.returncode,expected)

    def test_shell_integrity_checks_survive_hash_alias(self):
        h={n:"a"*64 for n in ("before-init_boot.img","before-abl.img","before-normal.efi","before-entries")}
        script=g.shell_transaction(self.p,"/data/adb/opd2515_17_103/tx-20261014_000000",h)
        # Android mksh defines hash as alias -t. Integrity checks must work despite that alias.
        functions=script[script.index('opd_sha256() {'):script.index('write_raw() {')]
        command="shopt -s expand_aliases\nalias hash='alias -t'\nBB=command\n"+functions+'eqhash "$1" "$2"\n'
        with tempfile.TemporaryDirectory(prefix='opd-sh-alias-') as directory:
            f=pathlib.Path(directory)/'fixture.img'
            f.write_bytes(b'partition-integrity-fixture')
            for digest,expected in ((g.sha(f),0),('0'*64,1)):
                result=subprocess.run([shell_executable(),'-c',command,'--',f.as_posix(),digest],capture_output=True)
                self.assertEqual(result.returncode,expected,result.stderr)


if __name__=="__main__": unittest.main()
