"""Download the pinned public Release and safely extract allowlisted research files."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import urllib.request
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    release = json.loads((root / 'release-assets.json').read_text(encoding='utf-8'))
    manifest = json.loads((root / 'materials-manifest.json').read_text(encoding='utf-8'))
    allow = {x['path'] for x in manifest['files']} | {'materials-manifest.json'}
    with tempfile.TemporaryDirectory(prefix='opd2515-materials-') as temp:
        packet = Path(temp) / 'materials.zip'
        req = urllib.request.Request(release['url'], headers={'User-Agent': 'OPD2515-research'})
        with urllib.request.urlopen(req, timeout=90) as source, packet.open('wb') as out:
            shutil.copyfileobj(source, out)
        with packet.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if packet.stat().st_size != release['bytes'] or digest != release['sha256']:
            raise ValueError('Release size/hash mismatch')
        with zipfile.ZipFile(packet) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != allow:
                raise ValueError('Archive differs from tracked allowlist')
            for name in names:
                path = PurePosixPath(name)
                target = root / name
                if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                    raise ValueError('Invalid archive member')
                if not target.resolve().is_relative_to(root) or target.is_symlink():
                    raise ValueError('Archive member escapes repository')
                if name == 'materials-manifest.json':
                    if archive.read(name) != (root / name).read_bytes():
                        raise ValueError('Manifest mismatch')
                    continue
                if target.exists():
                    with target.open('rb') as stream:
                        old = hashlib.file_digest(stream, 'sha256').hexdigest()
                    record = next(r for r in manifest['files'] if r['path'] == name)
                    if old != record['sha256']:
                        raise ValueError('Refusing to overwrite differing file: ' + name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, target.open('xb') as out:
                    shutil.copyfileobj(src, out)
    print('Pinned research materials extracted. No tools executed; no device contacted.')


if __name__ == '__main__':
    main()
