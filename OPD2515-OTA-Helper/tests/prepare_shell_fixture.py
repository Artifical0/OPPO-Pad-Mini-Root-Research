"""Create regular-file pseudo partitions to test shell hashing/write/rollback."""
import pathlib
import shutil
import sys

import test_review

ROOT = pathlib.Path(sys.argv[1])
PACKET = ROOT / "review-output-pass"
assert (ROOT / "DO-NOT-FLASH.txt").is_file()
dev = ROOT / "dev"
efi = ROOT / "efi"
packet = ROOT / "packet"
dev.mkdir(exist_ok=True)
efi.mkdir(exist_ok=True)
packet.mkdir(exist_ok=True)
for name in ("boot", "init_boot", "abl", "xbl", "xbl_config"):
    shutil.copy2(ROOT / "baseline" / (name + ".img"), dev / (name + "_b"))
    shutil.copy2(ROOT / "images" / (name + ".img"), dev / (name + "_a"))
    # Raw blocks have the baseline partition capacity, rather than payload length.
    expected = (dev / (name + "_b")).stat().st_size
    with (dev / (name + "_a")).open("ab") as stream:
        stream.write(bytes(expected - stream.tell()))
for name in ("ABL_normal.efi", "BOOTENTRIES"):
    shutil.copy2(ROOT / "baseline" / name, efi / name)
for name in ("plan.txt", "patched-init_boot.img", "ABL_normal.efi", "old-abl.img"):
    shutil.copy2(PACKET / name, packet / name)
for path in (ROOT / "firmware-fixture").glob("*.img"):
    for suffix in ("a", "b"): shutil.copy2(path, dev / (path.stem + "_" + suffix))
# Keep the shell integration fixture small. The full 39-firmware ledger is
# tested separately by the PC build; using one representative avoids thousands
# of Windows shell startups. This modified plan is never shipped or flashed.
plan = (packet / "plan.txt").read_text()
plan = "\n".join("firmware_names=engineering_cdt" if line.startswith("firmware_names=") else line for line in plan.splitlines()) + "\n"
(packet / "plan.txt").write_text(plan, newline="\n")
print("Desktop fixture prepared; no device access.")
