#!/usr/bin/env python3
"""Linux container stage: derive optional file ownership from ROCKNIX package outputs."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def owners(package_root, catalog):
    result = {}
    for module in catalog['modules']:
        names = set()
        for package in module['packages']:
            # The build's install_pkg directories are the actual installed
            # package file lists. Match the package name, not a version wildcard
            # that can accidentally include similarly prefixed packages.
            candidates = []
            for p in package_root.iterdir():
                marker = p/'.rocknix-package'
                if marker.is_file() and marker.read_text().strip() == package:
                    candidates.append(p)
            if not candidates:
                # ROCKNIX's marker can contain more metadata; directory versions
                # start with a digit or v<digit> in this locked package set.
                import re
                candidates = [p for p in package_root.iterdir()
                              if re.fullmatch(re.escape(package)+r'-(?:v?\d).*', p.name)]
            if len(candidates) != 1:
                raise ValueError('Expected one built package for '+package)
            for p in candidates[0].rglob('*'):
                if (p.is_file() or p.is_symlink()) and p.name != '.rocknix-package':
                    names.add(p.relative_to(candidates[0]).as_posix())
        result[module['id']] = sorted(names)
    return result


def main():
    workspace = Path('/work')/os.environ['KIT_VERSION']
    workspace.mkdir()
    root = workspace/'root'
    if root.exists() or Path('/task/kit').exists():
        raise ValueError('Installer workspace must be fresh')
    subprocess.run(['bash', '-ec', 'pigz -dc /factory.img.gz > "$1/factory.img"; '
                    'mcopy -i "$1/factory.img@@16777216" ::/SYSTEM "$1/SYSTEM"',
                    'extract', str(workspace)], check=True)
    subprocess.run(['unsquashfs', '-no-progress', '-no-xattrs', '-d', str(root), str(workspace/'SYSTEM')], check=True)
    catalog = json.loads(Path('/src/ports/rg353v/modules/catalog-v1.json').read_text())
    mapping = owners(Path('/cache/rocknix/build.ROCKNIX-RK3566.aarch64/install_pkg'), catalog)
    Path('/task/owners.json').write_text(json.dumps(mapping, indent=2)+'\n')
    subprocess.run(['python3', '/src/scripts/build-rg353v-modules.py', '--root', str(root),
                    '--owners', '/task/owners.json', '--tools', '/task/tools',
                    '--output', str(workspace/'kit')], check=True)
    # Only finished archives leave the Linux volume. A staging root may contain
    # mode-000 files and case-distinct paths that macOS bind mounts cannot hold.
    subprocess.run(['cp', '-a', str(workspace/'kit'), '/task/kit'], check=True)


if __name__ == '__main__':
    main()
