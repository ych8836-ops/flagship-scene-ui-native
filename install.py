"""Install into a selected native ComfyUI; never overwrite an existing node pack."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parent


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(comfy, *, spectrum=False, dry_run=False):
    comfy = Path(comfy).expanduser().resolve()
    if not (comfy / 'main.py').is_file() and (comfy / 'ComfyUI/main.py').is_file():
        comfy = comfy / 'ComfyUI'
    if not (comfy / 'main.py').is_file():
        raise ValueError('Choose the ComfyUI folder containing main.py, or its portable parent.')
    manifest = json.loads((ROOT / 'SHA256SUMS.json').read_text(encoding='utf-8'))
    for relative, expected in manifest.items():
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file() or checksum(source) != expected:
            raise ValueError('Package integrity check failed: ' + relative)
    for folder in ['custom_nodes']:
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc' and path.relative_to(ROOT).as_posix() not in manifest:
                raise ValueError('Unlisted node file in package: ' + str(path.relative_to(ROOT)))
    operations = []
    for folder in ['custom_nodes']:
        for source in sorted((ROOT / folder).iterdir()):
            if not source.is_dir():
                continue
            target = (comfy / 'custom_nodes' / source.name).resolve()
            if not target.is_relative_to(comfy):
                raise ValueError('Node destination is outside the selected ComfyUI: ' + str(target))
            if target.exists():
                raise ValueError('Existing node pack found; nothing installed: ' + str(target)
                                 + '\nUse a fresh ComfyUI, or manually review and back up existing packs first.')
            operations.append((source, target))
    workflow_dir = (comfy / 'user/default/workflows/FlagshipSceneUI').resolve()
    if not workflow_dir.is_relative_to(comfy):
        raise ValueError('Workflow destination is outside the selected ComfyUI.')
    for source in sorted((ROOT / 'workflows').glob('*.json')):
        target = workflow_dir / source.name
        if target.exists():
            raise ValueError('Workflow already exists; nothing installed: ' + str(target))
        operations.append((source, target))
    report = {'comfy': str(comfy), 'dry_run': dry_run, 'external_nodes_bundled': False,
              'spectrum_install_hint': 'Use tools/install_external_nodes.py --features spectrum' if spectrum else None,
              'destinations': [str(target) for source, target in operations],
              'python_packages_installed': False, 'models_downloaded': False, 'server_started': False}
    if not dry_run:
        for source, target in operations:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            else:
                shutil.copy2(source, target)
        for source, target in operations:
            paths = source.rglob('*') if source.is_dir() else [source]
            for path in paths:
                if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                    copied = target / path.relative_to(source) if source.is_dir() else target
                    if checksum(path) != checksum(copied):
                        raise OSError('Installed file verification failed: ' + str(copied))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy')
    parser.add_argument('--with-spectrum', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    selected = args.comfy or input('ComfyUI folder (contains main.py): ').strip().strip('"')
    try:
        print(json.dumps(install(selected, spectrum=args.with_spectrum, dry_run=args.dry_run), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
