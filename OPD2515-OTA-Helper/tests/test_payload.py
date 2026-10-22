import io
import pathlib
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import inspect_payload as payload


def vi(number):
    data = bytearray()
    while number > 127:
        data.append((number & 127) | 128); number >>= 7
    data.append(number)
    return bytes(data)


def uint(field, value):
    return vi(field << 3) + vi(value)


def blob(field, value):
    return vi((field << 3) | 2) + vi(len(value)) + value


def part(name, kind=0, old=False):
    info = uint(1, 8388608) + blob(2, bytes(32))
    data = blob(1, name.encode()) + blob(7, info) + blob(8, uint(1, kind))
    return blob(13, data + (blob(6, info) if old else b""))


def header(manifest):
    return b"CrAU" + struct.pack(">QQI", 2, len(manifest), 0) + manifest


class PayloadTests(unittest.TestCase):
    def test_init_boot_update_is_reported_as_boot_chain(self):
        result = payload.read_payload(io.BytesIO(header(part("init_boot"))))
        self.assertEqual(result["boot_chain_declared"], ["init_boot"])
        self.assertEqual(result["full_or_delta"], "self_contained")

    def test_source_copy_is_not_treated_as_full(self):
        result = payload.read_payload(io.BytesIO(header(part("abl", kind=4, old=True))))
        self.assertEqual(result["full_or_delta"], "source_dependent")
        self.assertTrue(result["partitions"][0]["uses_source_data"])

    def test_dynamic_system_only_still_needs_device_checks(self):
        result = payload.read_payload(io.BytesIO(header(part("system"))))
        self.assertEqual(result["boot_chain_declared"], [])
        self.assertEqual(result["partitions"][0]["category"], "system")

    def test_empty_manifest_is_not_safe_component_update(self):
        with self.assertRaisesRegex(ValueError, "没有可识别"):
            payload.read_payload(io.BytesIO(header(uint(3, 4096))))

    def test_duplicate_partition_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            payload.read_payload(io.BytesIO(header(part("abl") + part("abl"))))

    def test_truncated_protobuf_is_rejected(self):
        with self.assertRaises(ValueError):
            list(payload.fields(b"\x6a\x80"))

    def test_manifest_size_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "长度"):
            payload.read_payload(io.BytesIO(b"CrAU" + struct.pack(">QQI", 2, payload.LIMIT + 1, 0)))

    def test_zip_without_payload_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "component.zip"
            with zipfile.ZipFile(path, "w") as archive: archive.writestr("Photos.apk", b"APK fixture")
            report = payload.inspect(path)
            self.assertFalse(report["payload_found"])
            self.assertEqual(report["classification"], "UNKNOWN_CONTAINER_OR_COMPONENT_UPDATE")
            self.assertEqual(report["safety_decision"], "NOT_AUTHORIZED_TO_FLASH_OR_REBOOT")

    def test_recorded_500_manifest_lists_critical_partitions(self):
        report = payload.inspect(pathlib.Path(__file__).resolve().parent / "fixtures/500-payload-metadata.fixture")
        self.assertEqual(report["full_or_delta"], "self_contained")
        self.assertEqual(report["minor_version"], 9)
        self.assertTrue({"abl", "boot", "init_boot", "xbl", "xbl_config"}.issubset(report["boot_chain_declared"]))
        self.assertFalse(report["signature_verified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
