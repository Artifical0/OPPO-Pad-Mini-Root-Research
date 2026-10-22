"""Build a module-only ZIP. No device I/O and no boot images in the module."""
import hashlib
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)
tool_hashes = {}
for name, path in {
    "extractfv": WORKSPACE / "root-work/gbl-source/submodules/ablfvextractor/build/extractfv.exe",
    "patch_abl": WORKSPACE / "root-work/gbl-source/submodules/patcher/build/patch_abl.exe",
}.items():
    tool_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
assert tool_hashes == {
    "extractfv": "3381bdaec1270aaecf7c0d2e46158409c717301d1cd3e684b973b79c8530f0db",
    "patch_abl": "f2219fc52785fef65b3748cd9011ff64a119aeec33b62b9c5c86989b394cd7f6",
}
manifest = {"version": "0.1.0-rc2", "review_tool_hashes": tool_hashes,
            "gbl_commit": "2cf345a299df3f8b7172d6ad2fa5985e67fe53d6", "ksu_version": "3.3.0",
            "real_device_installed": False, "real_ota_tested": False, "module_files": {}}
packet = DIST / "OPD2515-OTA-Helper-0.1.0-rc2.zip"
with zipfile.ZipFile(packet, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
    for path in sorted((ROOT / "module").rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(ROOT / "module").as_posix()
        data = path.read_bytes()
        assert b"\r" not in data, f"CRLF: {name}"
        manifest["module_files"][name] = hashlib.sha256(data).hexdigest()
        info = zipfile.ZipInfo(name, (2026, 10, 12, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = ((0o100755 if path.suffix == ".sh" else 0o100644) << 16)
        output.writestr(info, data)
digest = hashlib.sha256(packet.read_bytes()).hexdigest()
manifest["zip_sha256"] = digest
manifest["zip_bytes"] = packet.stat().st_size
(ROOT / "build-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(DIST / (packet.name + ".sha256")).write_text(digest + "  " + packet.name + "\n", encoding="ascii")
print(packet)
print("SHA256=" + digest)
