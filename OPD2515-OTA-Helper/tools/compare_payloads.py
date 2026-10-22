"""Report every declared firmware change between two payload inspection reports.
Does not approve flashing. Other firmware changes need review beyond the rc2 five-image gate.
"""
import argparse
import json
import pathlib


def compare(current, target):
    if not current.get("payload_found") or not target.get("payload_found"):
        raise ValueError("两份报告都必须有已解析的 payload；不把组件包或未知包当作可放行")
    before = {p["name"]: p for p in current["partitions"]}
    after = {p["name"]: p for p in target["partitions"]}
    changed, missing = [], []
    for name, new in after.items():
        old = before.get(name)
        info = new.get("new") or {}
        previous = (old or {}).get("new") or {}
        if not info.get("sha256") or not previous.get("sha256"):
            missing.append(name)
        elif info != previous:
            changed.append({"name": name, "category": new["category"], "before": previous, "after": info})
    broader_firmware = [p["name"] for p in changed if p["category"] == "firmware_or_other" or p["name"] in {"xbl", "xbl_config", "xbl_ramdump"}]
    return {"changed_partitions": changed, "new_or_unverifiable_partitions": missing,
            "firmware_changes_beyond_root_image": broader_firmware,
            "not_in_target_payload": sorted(set(before) - set(after)),
            "requires_additional_firmware_review": bool(broader_firmware or missing),
            "safety_decision": "NOT_AUTHORIZED_TO_FLASH_OR_REBOOT",
            "note": "The running device and both slots must still be checked. A missing partition in an OTA does not prove which slot will boot."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=pathlib.Path)
    parser.add_argument("target", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        if args.out.exists(): raise ValueError("输出报告已存在")
        result = compare(json.loads(args.current.read_text(encoding="utf-8")), json.loads(args.target.read_text(encoding="utf-8")))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("改动分区：", ", ".join(p["name"] for p in result["changed_partitions"]) or "清单中未发现")
        print("需要额外固件检查：", result["requires_additional_firmware_review"])
        print("报告：", args.out)
    except (ValueError, OSError) as error:
        parser.exit(1, "BLOCKED/UNKNOWN: " + str(error) + "\n")


if __name__ == "__main__":
    main()
