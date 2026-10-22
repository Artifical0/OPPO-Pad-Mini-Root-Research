import copy
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import review
from test_review import fixtures


class PackageGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base, cls.images, cls.meta = fixtures()

    def packages(self):
        names = {n.removesuffix(".img"): d for n, d in self.images.items()}
        entries = [dict(name=n, category="boot_chain", new={"bytes": len(d), "sha256": review.sha(d)}) for n, d in names.items()]
        entries.extend(dict(name=n, category="firmware_or_other", new={"bytes": 4096, "sha256": "a" * 64}) for n in review.FIRMWARE_NAMES)
        old = dict(payload_found=True, full_or_delta="self_contained", manifest_sha256="0" * 64,
                   ota_metadata={"product_name": "OPD2515", "ota-type": "AB", "version_name": self.meta["build"]}, partitions=entries)
        new = copy.deepcopy(old)
        new["ota_metadata"]["version_name"] = "OPD2515_16.0.10.501(TEST_ONLY)"
        return old, new

    def run_gate(self, old, new, images=None):
        with patch.object(review, "inspect_ota", side_effect=[old, new]):
            return review.review_packages(pathlib.Path("current"), pathlib.Path("target"), self.base, self.meta,
                                          images or self.images, "OPD2515_16.0.10.501(TEST_ONLY)")

    def test_all_firmware_is_included_when_unchanged(self):
        firmware, _, _ = self.run_gate(*self.packages())
        self.assertEqual(set(firmware), review.FIRMWARE_NAMES)

    def test_tz_firmware_change_is_rejected(self):
        old, new = self.packages()
        next(p for p in new["partitions"] if p["name"] == "tz")["new"]["sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "tz"):
            self.run_gate(old, new)

    def test_partial_package_is_rejected(self):
        old, new = self.packages()
        for report in (old, new): report["partitions"] = [p for p in report["partitions"] if p["name"] != "modem"]
        with self.assertRaisesRegex(ValueError, "局部更新包"):
            self.run_gate(old, new)

    def test_extracted_image_from_wrong_package_is_rejected(self):
        images = self.images.copy()
        images["init_boot.img"] = self.base["init_boot.img"]
        with self.assertRaisesRegex(ValueError, "完整包 manifest"):
            self.run_gate(*self.packages(), images)

    def test_delta_payload_is_rejected(self):
        old, new = self.packages(); new["full_or_delta"] = "source_dependent"
        with self.assertRaisesRegex(ValueError, "增量"):
            self.run_gate(old, new)


if __name__ == "__main__": unittest.main(verbosity=2)
