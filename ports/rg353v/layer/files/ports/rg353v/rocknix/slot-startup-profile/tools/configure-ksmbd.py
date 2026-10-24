#!/usr/bin/env python3
"""Remove reviewed Samba runtime files after installing Slot's ksmbd backend."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def prune(root, policy=None, dependency_check=None):
    root = Path(root).resolve()
    marker = root / 'usr/sbin/ksmbd.mountd'
    if not marker.exists():
        raise ValueError('Install the ksmbd backend before removing Samba')
    policy = Path(policy) if policy else HERE.parent / 'config/backend-prune.json'
    plan = json.loads(policy.read_text())
    if plan.get('schema') != 1 or plan.get('backend') != 'ksmbd':
        raise ValueError('Unexpected SMB backend policy')
    files = []
    for name, entry in plan['remove'].items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or not name.startswith(('etc/samba/', 'usr/')) or '/licenses/' in name:
            raise ValueError('Unsafe legacy backend path')
        p = root / rel
        if any(q.is_symlink() for q in p.parents if q != root and root in q.parents):
            raise ValueError('Legacy backend path crosses a symlink')
        if p.is_symlink():
            if str(p.readlink()) != entry.get('link'):
                raise ValueError('Changed legacy backend symlink: ' + name)
        elif p.exists():
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != entry.get('sha256'):
                raise ValueError('Review changed legacy backend file: ' + name)
        else:
            continue
        files.append((p, entry))
    if dependency_check is None:
        spec = importlib.util.spec_from_file_location('image_dependencies', HERE / 'configure-image-prune.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dependency_check = module.check_dependencies
    dependency_check(root, set(plan['remove']))
    # A changed package may add files outside the reviewed receipt. Do not ship
    # an accidentally mixed backend or silently delete the new payload.
    remaining = [p for folder, pattern in [('usr/lib', '*samba*'), ('usr/sbin', '*smbd*'),
                 ('usr/bin', 'smb*')] for p in (root / folder).glob(pattern)
                 if (p.is_file() or p.is_symlink()) and p.name not in ('ksmbd.mountd', 'ksmbd.control')
                 and str(p.relative_to(root)) not in plan['remove']]
    if remaining:
        raise ValueError('Unreviewed legacy SMB files remain: ' + ', '.join(str(p.relative_to(root)) for p in remaining))
    for p, _ in files:
        p.unlink()
    result = {'backend': 'ksmbd', 'removed_files': len(files),
              'removed_bytes': sum(x.get('bytes', 0) for _, x in files),
              'retained_elf_dependencies': 'passed'}
    out = root / 'usr/share/slot/hardware/backend-prune.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    if files or not out.exists():
        out.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prune(args.root), indent=2))
