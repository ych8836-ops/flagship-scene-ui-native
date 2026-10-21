"""Explicitly install separately sourced dependencies into a user-selected ComfyUI."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def selected_comfy(value):
    root = Path(value).expanduser().resolve()
    if not (root / 'main.py').is_file() and (root / 'ComfyUI/main.py').is_file():
        root = root / 'ComfyUI'
    if not (root / 'main.py').is_file():
        raise ValueError('Select the ComfyUI folder containing main.py.')
    return root


def download(item, cache=None):
    candidate = Path(cache) / (item['id'] + ('.zip' if 'repo' in item else '.download')) if cache else None
    if candidate and candidate.is_file():
        data = candidate.read_bytes()
    else:
        if not item['url'].startswith('https://'):
            raise ValueError('HTTPS source required')
        request = urllib.request.Request(item['url'], headers={'User-Agent': 'Flagship-Native-Dependencies'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        if candidate:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(data)
    if hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('Upstream checksum mismatch: ' + item['id'])
    return data


def install(comfy, features, *, dry_run=False, cache=None):
    root = selected_comfy(comfy)
    lock = json.loads((ROOT / 'external_dependencies.lock.json').read_text(encoding='utf-8'))
    items = [x for x in lock['repositories'] + lock['files'] if x['feature'] in features]
    targets = []
    for item in items:
        target = (root / item['path']).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError('Dependency destination escapes selected ComfyUI')
        if target.exists():
            if 'repo' in item:
                marker = target / '.flagship-external.json'
                same = marker.is_file() and json.loads(marker.read_text(encoding='utf-8'))['sha256'] == item['sha256']
            else:
                same = target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == item['sha256']
            if not same:
                raise ValueError('Existing dependency is preserved; review it manually: ' + str(target))
        targets.append((item, target))
    report = {'comfy': str(root), 'dry_run': dry_run,
              'sources': [{'id': x['id'], 'url': x['url'], 'destination': str(p)} for x, p in targets],
              'models_downloaded': False, 'python_packages_installed': False}
    if dry_run:
        return report
    # Validate all new payloads before copying any dependency.
    payloads = [(x, p, download(x, cache)) for x, p in targets if not p.exists()]
    for item, target, data in payloads:
        target.parent.mkdir(parents=True, exist_ok=True)
        if 'repo' in item:
            with tempfile.TemporaryDirectory(prefix='flagship-external-', dir=target.parent) as temporary:
                payload = Path(temporary) / 'payload'
                payload.mkdir()
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for info in archive.infolist():
                        parts = Path(info.filename).parts[1:]
                        if not parts:
                            continue
                        output = (payload / Path(*parts)).resolve()
                        if not output.is_relative_to(payload) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError('Unsafe path in external archive')
                        if info.is_dir():
                            output.mkdir(parents=True, exist_ok=True)
                        else:
                            output.parent.mkdir(parents=True, exist_ok=True)
                            output.write_bytes(archive.read(info))
                shutil.copytree(payload, target)
                (target / '.flagship-external.json').write_text(json.dumps(item, indent=2), encoding='utf-8')
        else:
            target.write_bytes(data)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy')
    parser.add_argument('--features', nargs='+', choices=['core', 'camera', 'spectrum', 'repair', 'extra'], default=['core', 'camera'])
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    selected = args.comfy or input('ComfyUI folder (contains main.py): ').strip().strip('"')
    print(json.dumps(install(selected, set(args.features), dry_run=args.dry_run, cache=args.cache), ensure_ascii=False, indent=2))
