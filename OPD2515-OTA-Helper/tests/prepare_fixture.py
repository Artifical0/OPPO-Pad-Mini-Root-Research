"""Create desktop-only fixtures; outputs contain synthetic XBL, never flash them."""
import hashlib
import pathlib
import sys
import zipfile
from test_payload import blob, uint, header

from test_review import fixtures
import review

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=False)
base, target, meta = fixtures()
baseline = OUT / "baseline"
images = OUT / "images"
baseline.mkdir()
images.mkdir()
for name, data in base.items():
    (baseline / name).write_bytes(data)
(baseline / "device.txt").write_text("".join(f"{k}={v}\n" for k, v in meta.items()), encoding="utf-8", newline="\n")
(baseline / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in sorted(baseline.iterdir())), encoding="ascii")
for name, data in target.items():
    (images / name).write_bytes(data)
firmware = OUT / "firmware-fixture"
firmware.mkdir()
for name in review.FIRMWARE_NAMES:
    (firmware / (name + ".img")).write_bytes(("FAKE-FIRMWARE-" + name).encode().ljust(4096, b"\0"))
def package(path, build):
    manifest = uint(12, 9)
    entries = {name.removesuffix(".img"): data for name, data in target.items()}
    entries.update({name: (firmware / (name + ".img")).read_bytes() for name in review.FIRMWARE_NAMES})
    for name, data in sorted(entries.items()):
        info = uint(1, len(data)) + blob(2, hashlib.sha256(data).digest())
        manifest += blob(13, blob(1, name.encode()) + blob(7, info) + blob(8, uint(1, 0)))
    with zipfile.ZipFile(path, "x") as archive:
        archive.writestr("payload.bin", header(manifest))
        archive.writestr("META-INF/com/android/metadata", "product_name=OPD2515\nota-type=AB\nversion_name=" + build + "\n")
package(OUT / "current-TEST-ONLY.zip", meta["build"])
package(OUT / "target-TEST-ONLY.zip", "OPD2515_16.0.10.501(TEST_ONLY)")
(OUT / "DO-NOT-FLASH.txt").write_text("DESKTOP TEST FIXTURE. SYNTHETIC XBL. NOT REAL OTA. NEVER FLASH.\n", encoding="ascii")
print(OUT)
