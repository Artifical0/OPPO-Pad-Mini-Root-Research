"""Deterministic module-only build; no firmware, downloads, or device access."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = "0.2.0-rc1"


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    packet = out / f"OPD2515-OTA-Helper-{VERSION}.zip"
    manifest = {"version": VERSION, "real_device_installed": False, "real_ota_tested": False, "files": {}}
    with zipfile.ZipFile(packet, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted((ROOT / "module").rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(ROOT / "module").as_posix()
            data = path.read_bytes()
            if path.is_symlink() or b"\r" in data:
                raise ValueError(f"Expected regular LF source: {name}")
            info = zipfile.ZipInfo(name, (2026, 10, 23, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            archive.writestr(info, data, compresslevel=9)
            manifest["files"][name] = hashlib.sha256(data).hexdigest()
    manifest.update(zip_sha256=hashlib.sha256(packet.read_bytes()).hexdigest(), zip_bytes=packet.stat().st_size)
    (out / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "SHA256SUMS.txt").write_text(manifest["zip_sha256"] + "  " + packet.name + "\n", encoding="ascii", newline="\n")
    return packet, manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    packet, manifest = build(args.out)
    print(packet)
    print(manifest["zip_sha256"])
