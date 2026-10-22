import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import compare_payloads


def report():
    return {"payload_found": True, "partitions": [
        {"name": "system", "category": "system", "new": {"bytes": 4096, "sha256": "a" * 64}},
        {"name": "tz", "category": "firmware_or_other", "new": {"bytes": 4096, "sha256": "b" * 64}},
    ]}


class CompareTests(unittest.TestCase):
    def test_tz_change_is_not_covered_by_five_image_check(self):
        old = report(); new = copy.deepcopy(old)
        new["partitions"][1]["new"]["sha256"] = "c" * 64
        result = compare_payloads.compare(old, new)
        self.assertTrue(result["requires_additional_firmware_review"])
        self.assertEqual(result["firmware_changes_beyond_root_image"], ["tz"])

    def test_matching_reports_never_approve_reboot(self):
        result = compare_payloads.compare(report(), report())
        self.assertFalse(result["requires_additional_firmware_review"])
        self.assertEqual(result["safety_decision"], "NOT_AUTHORIZED_TO_FLASH_OR_REBOOT")

    def test_unknown_component_report_is_blocked(self):
        with self.assertRaises(ValueError): compare_payloads.compare(report(), {"payload_found": False})

    def test_new_firmware_partition_needs_review(self):
        old = report(); new = copy.deepcopy(old)
        new["partitions"].append({"name": "aop", "category": "firmware_or_other", "new": {"sha256": "c" * 64, "bytes": 4096}})
        result = compare_payloads.compare(old, new)
        self.assertTrue(result["requires_additional_firmware_review"])
        self.assertEqual(result["new_or_unverifiable_partitions"], ["aop"])


if __name__ == "__main__": unittest.main(verbosity=2)
