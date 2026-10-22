"""Verify every allowlisted research asset; never executes tools or contacts a device."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=Path('.'))
    args = parser.parse_args()
    root = args.directory.resolve()
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'materials-manifest.json').read_text(encoding='utf-8'))
    failed = []
    for record in manifest['files']:
        path = root / record['path']
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
            failed.append(record['path'] + ': missing or invalid path')
            continue
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != record['sha256'] or path.stat().st_size != record['bytes']:
            failed.append(record['path'] + ': digest/size mismatch')
    print(json.dumps({'checked': len(manifest['files']), 'failures': failed}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
