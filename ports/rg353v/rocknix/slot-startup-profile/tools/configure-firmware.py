#!/usr/bin/env python3
"""Prune foreign radio firmware only after the complete opt-in image is installed."""
import argparse
import hashlib
import json
from pathlib import Path


def prune(root, policy_path):
    root = root.resolve()
    profile = json.loads((root/'usr/share/slot/os-profile.json').read_text())
    if profile.get('userspace_profile', 'baseline') == 'baseline':
        return {'removed': [], 'profile': 'baseline'}
    hardware = json.loads((root/'usr/share/slot/hardware/profile.json').read_text())
    if (profile.get('device') != 'rg353v' or profile['userspace_profile'] != 'rg353v-lean-v1'
            or hardware.get('model') != 'anbernic,rg353v'
            or hardware.get('panel') != 'anbernic,rg353v-panel-v2'):
        raise ValueError('Unqualified firmware hardware profile')
    policy = json.loads(policy_path.read_text())
    if policy['schema'] != 1:
        raise ValueError('Unknown firmware policy')
    firmware = root/'usr/lib/kernel-overlays/base/lib/firmware'

    def safe(name):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Invalid firmware path')
        path = firmware/relative
        for parent in (path, *path.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError('Firmware path crosses symlink: '+name)
        return path

    retained = {}
    for name, wanted in policy['required_sha256'].items():
        path = safe(name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != wanted:
            raise ValueError('Review changed required firmware: '+name)
        retained[name] = actual
    candidates = set()
    for name in policy['remove_families']:
        directory = safe(name)
        if directory.exists():
            candidates.update(p for p in directory.rglob('*') if not p.is_dir() or p.is_symlink())
    candidates.update(safe(name) for name in policy['remove_files'] if safe(name).exists())
    for name, keep in policy['keep_in_family'].items():
        directory = safe(name)
        if directory.exists():
            # Keep licensing/readme material and the actual board's radio files.
            candidates.update(p for p in directory.glob('*.bin') if p.name not in keep)
    removed = []
    for path in sorted(candidates):
        relative = str(path.relative_to(firmware))
        if relative in retained:
            raise ValueError('Firmware policy removes a required file')
        safe(relative)  # Preflight the entire plan before deleting anything.
        if not path.is_file():
            raise ValueError('Firmware removal is not a regular file: '+relative)
        removed.append({'path': relative, 'bytes': path.stat().st_size,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    for item in removed:
        (firmware/item['path']).unlink()
    report = {'profile': 'rg353v-lean-v1', 'removed': removed, 'retained_sha256': retained,
              'removed_bytes': sum(item['bytes'] for item in removed)}
    output = root/'usr/share/slot/hardware/firmware-trim.json'
    if removed or not output.exists():
        output.write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--policy', type=Path, default=Path(__file__).parents[1]/'config/firmware-rg353v.json')
    args = parser.parse_args()
    print(json.dumps(prune(args.root, args.policy), indent=2))
