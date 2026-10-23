import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "OPD2515-OTA-Helper/tests"))
import prepare_update as update
from test_review import fixtures
from test_payload import blob, uint, header

spec = importlib.util.spec_from_file_location("module_build", HERE / "build.py")
module_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module_build)


def fixture():
    base, target, meta = fixtures()
    meta.update(schema="2", ksu_version="ksud 3.3.1 (uapi: 5)", raw_device_state="unlocked", raw_verifiedbootstate="orange")
    base["BOOTENTRIES"] += b"$500 EFI - only with verified 500 slot:ABL_500.efi\n$17 EFI:ABL_17.efi\n"
    return base, target, meta


def baseline_archive(path, base, meta, extra=None):
    data = dict(base)
    data["device.txt"] = "".join(f"{k}={v}\n" for k, v in meta.items()).encode()
    data["SHA256SUMS"] = "".join(f"{update.sha(v)}  {k}\n" for k, v in sorted(data.items())).encode()
    with tarfile.open(path, "w:gz") as archive:
        for name, value in data.items():
            entry = tarfile.TarInfo("./" + name)
            entry.size = len(value)
            archive.addfile(entry, io.BytesIO(value))
        if extra:
            entry = tarfile.TarInfo(extra)
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            archive.addfile(entry)


def full_fixture(path, images, build, altered=None):
    entries = {n.removesuffix(".img"): v for n, v in images.items()}
    entries.update({n: ("TEST-FIRMWARE-" + n).encode().ljust(4096, b"\0") for n in update.legacy.FIRMWARE_NAMES})
    if altered:
        entries[altered] += b"changed"
    manifest = uint(3, 4096) + uint(12, 9)
    for name, data in sorted(entries.items()):
        info = uint(1, len(data)) + blob(2, hashlib.sha256(data).digest())
        manifest += blob(13, blob(1, name.encode()) + blob(7, info) + blob(8, uint(1, 0)))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("payload.bin", header(manifest))
        archive.writestr("META-INF/com/android/metadata", f"product_name=OPD2515\nota-type=AB\nversion_name={build}\n")
    return entries


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.base, self.images, self.meta = fixture()

    def test_schema2_current_ksu_extended_menu_roundtrip(self):
        path = self.out / "base.tar.gz"
        baseline_archive(path, self.base, self.meta)
        base, meta = update.read_baseline(path)
        self.assertEqual(base["BOOTENTRIES"], self.base["BOOTENTRIES"])
        self.assertEqual(meta["ksu_version"], "ksud 3.3.1 (uapi: 5)")

    def test_legacy_export_requires_new_export(self):
        self.meta["schema"] = "1"
        path = self.out / "base.tar.gz"
        baseline_archive(path, self.base, self.meta)
        with self.assertRaisesRegex(ValueError, "重新导出"):
            update.read_baseline(path)

    def test_tar_path_links_and_duplicates_blocked(self):
        for extra in ("../boot.img", "./boot.img", "link"):
            with self.subTest(extra=extra):
                path = self.out / "base.tar.gz"
                baseline_archive(path, self.base, self.meta, extra)
                with self.assertRaisesRegex(ValueError, "异常路径"):
                    update.read_baseline(path)

    def test_menu_default_cannot_be_fake_locked(self):
        for menu in (b"Fake:fake.efi\n", self.base["BOOTENTRIES"] + b"$Other:../bad.efi\n"):
            with self.assertRaises(ValueError):
                update.validate_menu(menu)

    def test_unsupported_ksu_and_spoofed_raw_state_blocked(self):
        for key, value in (("ksu_version", "ksud 9.0"), ("raw_device_state", "locked")):
            with self.subTest(key=key):
                meta = dict(self.meta, **{key: value})
                path = self.out / "base.tar.gz"
                baseline_archive(path, self.base, meta)
                with self.assertRaises(ValueError):
                    update.read_baseline(path)

    def test_signed_package_pin_and_unsigned_rejection(self):
        path = self.out / "ota.zip"
        full_fixture(path, self.images, self.meta["build"])
        with self.assertRaises(ValueError):
            update.verify_official(path)
        with patch.object(update, "verify", return_value={"whole_file_signature_valid": True, "all_entry_crcs_valid": True, "signer_certificate_sha256": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "签名证书"):
                update.verify_official(path)

    def test_full_plan_packet_and_changed_firmware_rejection(self):
        current, target = self.out / "current.zip", self.out / "target.zip"
        build = "OPD2515_16.0.10.501(TEST_ONLY)"
        full_fixture(current, self.images, self.meta["build"])
        full_fixture(target, self.images, build)
        plan, report = update.make_plan(self.base, self.meta, self.images, build, current, target)
        self.assertEqual(plan["schema"], 2)
        self.assertEqual(len(plan["firmware_names"].split(",")), 39)
        packet, digest = update.write_packet(self.out, self.base, plan, self.base["ABL_normal.efi"], self.base["init_boot.img"])
        self.assertEqual(update.sha(packet.read_bytes()), digest)
        with zipfile.ZipFile(packet) as archive:
            self.assertEqual(set(archive.namelist()), {"plan.txt", "old-abl.img", "ABL_normal.efi", "patched-init_boot.img"})
            self.assertNotIn(b"\r", archive.read("plan.txt"))
        full_fixture(target, self.images, build, altered="tz")
        with self.assertRaisesRegex(ValueError, "tz"):
            update.make_plan(self.base, self.meta, self.images, build, current, target)

    def test_same_version_and_downgrade_rejected_before_package_access(self):
        for build in (self.meta["build"], "OPD2515_16.0.10.499(CN01)"):
            with self.assertRaisesRegex(ValueError, "只支持升级"):
                update.make_plan(self.base, self.meta, self.images, build, self.out / "missing", self.out / "missing")

    def test_module_build_reproducible_and_image_free(self):
        one, manifest = module_build.build(self.out / "one")
        two, _ = module_build.build(self.out / "two")
        self.assertEqual(one.read_bytes(), two.read_bytes())
        self.assertFalse(manifest["real_device_installed"])
        with zipfile.ZipFile(one) as archive:
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            self.assertTrue(all(not n.endswith((".img", ".efi", ".exe")) for n in archive.namelist()))
            self.assertIn("bin/guards.sh", archive.namelist())

    @unittest.skipUnless(sys.platform == "win32", "Pinned native patch tools run on Windows")
    def test_real_native_500_patch_on_desktop(self):
        # Real signed input, synthetic XBL is never passed to a device.
        with tempfile.TemporaryDirectory(prefix="opd-test-", dir=os.environ.get("PUBLIC")) as ascii_temp:
            runtime = os.environ.get("OPD_RUNTIME_DIR")
            normal, patched = update.patch_images(self.images, self.meta, self.out, runtime_dir=runtime, temp_root=ascii_temp)
        self.assertEqual(update.sha(normal), "6fa5baed02ca05743491afe32e30470f1ec1afb0cca94fe1cd6dbd560242e503")
        self.assertEqual(len(patched), 8388608)


def shell_fixture(out):
    base, images, meta = fixture()
    out.mkdir(parents=True, exist_ok=False)
    (out / "NEVER-FLASH.txt").write_text("Synthetic desktop fixture. No device access.\n")
    firmware = full_fixture(out / "current.zip", images, meta["build"])
    target_build = "OPD2515_16.0.10.501(TEST_ONLY)"
    full_fixture(out / "target.zip", images, target_build)
    plan, _ = update.make_plan(base, meta, images, target_build, out / "current.zip", out / "target.zip")
    # Different PE bytes, valid production plan hashing; no claim of target bootability.
    normal = base["ABL_normal.efi"] + b"DESKTOP-TEST"
    packet = out / "packet"
    packet.mkdir()
    archive, _ = update.write_packet(packet, base, plan, normal, base["init_boot.img"])
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            (packet / name).write_bytes(source.read(name))
    for name, extra in (("duplicate.zip", "plan.txt"), ("path.zip", "../plan.txt")):
        shutil.copyfile(archive, out / name)
        with zipfile.ZipFile(out / name, "a") as modified:
            modified.writestr(extra, "schema=2\n")
    encoded = struct.pack("<II", 0, 40) + "2400346954240a5de495a1debc81429dd012d7b7".encode("utf-16-le") + bytes(4)
    words = struct.unpack("<" + "I" * (len(encoded) // 4), encoded)
    (out / "hal-hash.txt").write_text("Result: Parcel(" + " ".join(f"{w:08x}" for w in words) + ")\n", newline="\n")
    dev, efi = out / "dev", out / "efi"
    dev.mkdir(); efi.mkdir()
    for n in ("ABL_normal.efi", "BOOTENTRIES"):
        (efi / n).write_bytes(base[n])
    for n in update.legacy.FIRMWARE_NAMES:
        for slot in ("a", "b"):
            (dev / f"{n}_{slot}").write_bytes(firmware[n])
    for n in update.NAMES:
        for slot, source in (("b", base), ("a", images)):
            (dev / f"{n}_{slot}").write_bytes(source[n + ".img"].ljust(len(base[n + ".img"]), b"\0"))
    (dev / "efisp").write_bytes(b"not-a-device")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--shell-fixture":
        shell_fixture(Path(sys.argv[2]))
    else:
        unittest.main()
