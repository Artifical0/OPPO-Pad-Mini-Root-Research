"""Tests use existing 500 images and an xbl_config ELF as a synthetic XBL fixture.
They do not establish real XBL compatibility or a real future OTA result.
"""
import copy
import hashlib
import pathlib
import struct
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import review
from cryptography.exceptions import InvalidSignature

ROOT = review.WORKSPACE
BACKUP = ROOT / "root-work/partitions/locked-20261012_120915"
PATCHED = ROOT / "root-work/patched/KernelSU-v3.3.0-slot-b-20261012_145008/kernelsu_patched-init_boot.img"
NORMAL = ROOT / "root-work/gbl/compatibility-20261012_122445/current_b/ABL_normal.efi"


def fixtures():
    config = (BACKUP / "xbl_config_b.img").read_bytes()
    base = {
        "boot.img": (BACKUP / "boot_b.img").read_bytes(),
        "init_boot.img": PATCHED.read_bytes(),
        "abl.img": (ROOT / "root-work/coolapk-original/oppo_pad_mini_root_file/abl_a.img").read_bytes(),
        "xbl.img": config,  # Synthetic XBL; the real XBL has not yet been exported.
        "xbl_config.img": config,
        "ABL_normal.efi": NORMAL.read_bytes(),
        "BOOTENTRIES": b"Normal Boot:ABL_normal.efi\n%Android Tools:tools\\ENTRIES\n",
    }
    target = {"boot.img": base["boot.img"], "init_boot.img": (BACKUP / "init_boot_b.img").read_bytes(),
              "abl.img": (BACKUP / "abl_b.img").read_bytes(), "xbl.img": config,
              "xbl_config.img": (ROOT / "extracted_images/xbl_config.img").read_bytes()}
    meta = dict(schema="1", model="OPD2515", active_slot="b", target_slot="a", build="OPD2515_16.0.10.500(CN01)",
                kernel=review.kernel_release(base["boot.img"]), bds_hash=review.BDS_HASH)
    for name in ("boot", "init_boot", "abl", "xbl", "xbl_config"):
        meta["size_" + name] = meta["target_size_" + name] = str(len(base[name + ".img"]))
    return base, target, meta


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base, cls.target, cls.meta = fixtures()

    def plan(self, target=None, build="OPD2515_16.0.10.501(TEST_ONLY)"):
        return review.make_plan(self.base, self.meta, target or self.target, build)

    def test_real_abl_signatures_and_metadata_match(self):
        plan, report = self.plan()
        self.assertEqual(plan["target_slot"], "a")
        self.assertEqual(report["abl_auth"]["arb"], 0)
        self.assertTrue(report["abl_auth"]["signature_verified"])

    def test_xbl_config_unused_tail_padding_is_ignored(self):
        self.assertNotEqual(len(self.base["xbl_config.img"]), len(self.target["xbl_config.img"]))
        self.assertEqual(review.canonical(self.base["xbl_config.img"]), review.canonical(self.target["xbl_config.img"]))

    def test_changed_xbl_load_segment_is_blocked(self):
        target = self.target.copy()
        data = bytearray(target["xbl.img"])
        segs, _ = review.elf_segments(data)
        segment = next(s for s in segs if s["off"] > 0 and s["size"] > 100)
        data[segment["off"] + 80] ^= 1
        target["xbl.img"] = bytes(data)
        with self.assertRaisesRegex(ValueError, "xbl"):
            self.plan(target)

    def test_signed_arb_tampering_is_blocked(self):
        target = self.target.copy()
        data = bytearray(target["abl.img"])
        segs, _ = review.elf_segments(data)
        segment = next(s for s in segs if (s["flags"] >> 24) & 7 == 2)
        data[segment["off"] + 40 + 24 + 8] = 1
        target["abl.img"] = bytes(data)
        with self.assertRaises(InvalidSignature):
            self.plan(target)

    def test_new_kmi_generation_is_blocked(self):
        target = self.target.copy()
        target["boot.img"] = target["boot.img"].replace(b"6.12.58-android16-6-", b"6.12.58-android16-7-")
        with self.assertRaisesRegex(ValueError, "KMI"):
            self.plan(target)

    def test_inconsistent_kernel_versions_are_blocked(self):
        target = self.target.copy()
        target["boot.img"] = target["boot.img"].replace(b"6.12.58-android16-6-", b"6.12.58-android16-7-", 1)
        with self.assertRaisesRegex(ValueError, "唯一"):
            self.plan(target)

    def test_wrong_init_boot_is_blocked(self):
        target = self.target.copy()
        target["init_boot.img"] = self.target["boot.img"]
        with self.assertRaisesRegex(ValueError, "类型"):
            self.plan(target)

    def test_elf_truncated_segments_are_blocked(self):
        with self.assertRaisesRegex(ValueError, "越界"):
            review.canonical(self.base["xbl_config.img"][:1000])

    def test_source_build_cannot_be_reused_as_target(self):
        with self.assertRaisesRegex(ValueError, "版本号"):
            self.plan(build=self.meta["build"])

    def test_duplicate_manifest_keys_are_blocked(self):
        with self.assertRaisesRegex(ValueError, "字段"):
            review.read_kv(b"schema=1\nschema=2\n")

    def test_real_500_normal_patch_log_is_accepted(self):
        log = (ROOT / "evidence/500/patch-normal-log.txt").read_text(encoding="utf-8")
        review.validate_normal_patch_log(log)

    def test_oplus_nonfatal_failure_is_blocked(self):
        log = (ROOT / "evidence/500/patch-normal-log.txt").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "补丁失败"):
            review.validate_normal_patch_log(log + "\nOPlus Warning: patch_fastboot failed\n")

    def test_missing_fastboot_success_is_blocked(self):
        log = (ROOT / "evidence/500/patch-normal-log.txt").read_text(encoding="utf-8")
        log = "\n".join(line for line in log.splitlines() if "fastboot always enabled" not in line)
        with self.assertRaisesRegex(ValueError, "fastboot"):
            review.validate_normal_patch_log(log)

    def test_wrong_boot_patch_mode_is_blocked(self):
        log = (ROOT / "evidence/500/patch-normal-log.txt").read_text(encoding="utf-8").replace("Patch mode: normal", "Patch mode: fake_locked")
        with self.assertRaisesRegex(ValueError, "Normal Boot"):
            review.validate_normal_patch_log(log)

    def test_metadata_change_with_valid_signature_is_blocked(self):
        from unittest.mock import patch
        original = review.authenticate_abl
        calls = []
        def authenticated(data):
            result = original(data)
            calls.append(True)
            if len(calls) == 2:
                result["arb"] = 1
            return result
        with patch.object(review, "authenticate_abl", side_effect=authenticated):
            with self.assertRaisesRegex(ValueError, "ARB"):
                self.plan()


if __name__ == "__main__":
    unittest.main(verbosity=2)
