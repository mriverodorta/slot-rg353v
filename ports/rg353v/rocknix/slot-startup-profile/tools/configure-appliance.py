#!/usr/bin/env python3
"""Apply reviewed RG353V-only payload reductions to an assembled image."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import shutil


HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compact_gconv(root):
    """Retain Unicode and Samba DOS/Latin conversions with consistent aliases."""
    folder = root / 'usr/lib/gconv'
    files = [folder / 'gconv-modules', *sorted((folder / 'gconv-modules.d').glob('*.conf'))]
    aliases, modules = [], []
    available = {p.stem for p in folder.glob('*.so')}
    for path in files:
        for line in path.read_text().splitlines():
            fields = line.split('#', 1)[0].split()
            if len(fields) >= 4 and fields[0] == 'module' and fields[3] in available:
                modules.append(line)
            elif len(fields) == 3 and fields[0] == 'alias':
                aliases.append((fields, line))
    supported = {'INTERNAL', 'UTF-8//', 'ASCII//', 'ANSI_X3.4-1968//'}
    for line in modules:
        supported.update(line.split()[1:3])
    selected = set()
    while True:
        before = len(selected)
        for fields, line in aliases:
            if fields[2] in supported:
                supported.add(fields[1])
                selected.add(line)
        if len(selected) == before:
            break
    for path in files[1:]:
        path.unlink()
    (folder / 'gconv-modules.cache').unlink(missing_ok=True)
    files[0].write_text('# RG353V Unicode, Latin and Samba DOS conversions.\n' +
                        '\n'.join(sorted(selected) + modules) + '\n')


def deduplicate_sdl(root):
    """Keep the normal runtime filename and make the alternate directory an alias."""
    main = root / 'usr/lib/libSDL2-2.0.so.0.3200.10'
    duplicate = root / 'usr/lib/glesonly' / main.name
    if duplicate.is_symlink():
        if duplicate.readlink() != Path('../' + main.name):
            raise ValueError('Unexpected SDL alias')
        return 0
    if not duplicate.exists():
        return 0
    if main.is_symlink() or hashlib.sha256(main.read_bytes()).digest() != hashlib.sha256(duplicate.read_bytes()).digest():
        raise ValueError('SDL variants differ; review before consolidation')
    size = duplicate.stat().st_size
    duplicate.unlink()
    duplicate.symlink_to('../' + main.name)
    return size


def stage_boot_artifacts(root, destination):
    """ROCKNIX's factory-image writer still needs these outside SYSTEM."""
    source = root / 'usr/share/bootloader'
    if not source.is_dir() or source.is_symlink():
        raise ValueError('Missing factory bootloader build inputs')
    files = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in source.rglob('*') if p.is_file() and not p.is_symlink()}
    destination = Path(destination)
    receipt = destination / '.slot-build-inputs.json'
    if destination.exists():
        if not receipt.is_file() or json.loads(receipt.read_text()) != files:
            raise ValueError('Changed cached bootloader inputs; use a fresh build-cache destination')
        for name, digest in files.items():
            if hashlib.sha256((destination / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Corrupt bootloader build-input cache')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)
    receipt.write_text(json.dumps(files, sort_keys=True, indent=2) + '\n')


def configure(root, policy=None, boot_artifacts=None):
    root = Path(root).resolve()
    image = json.loads((root / 'usr/share/slot/os-profile.json').read_text())
    if boot_artifacts is not None:
        stage_boot_artifacts(root, boot_artifacts)
    if image.get('userspace_profile') != 'rg353v-lean-v1' or image.get('build_profile') != 'normal':
        return {'profile': 'untrimmed'}
    # Validate the entire exact-hash trim and ELF graph before any payload
    # deletion. This also checks the pinned board, panel and graphics libraries.
    # Remove Samba before its now-orphaned GnuTLS dependency family. Checking
    # the final trim while Samba is present would correctly reject that plan.
    sharing = None
    if (root / 'usr/sbin/ksmbd.mountd').exists():
        backend = load('ksmbd_backend_pruning', 'configure-ksmbd.py')
        sharing = backend.prune(root)
    pruning = load('appliance_pruning', 'configure-image-prune.py')
    result = pruning.prune(root, policy or HERE.parent / 'config/appliance-prune.json',
                           report_name='appliance-prune.json')
    startup = load('appliance_startup', 'configure-startup.py')
    metadata = root / 'usr/share/slot/hardware/profile.json'
    hardware = json.loads(metadata.read_text())
    database, defaults = startup.fixed_hwdb(root)
    hardware.update(hwdb_sha256=startup.digest(database), default_overrides=defaults,
                    hwdb_scope='rg353v-built-in-inputs')
    hardware.pop('hwdb_no_overrides_sha256', None)
    metadata.write_text(json.dumps(hardware, indent=2) + '\n')
    script = root / 'usr/bin/slot-hwdb'
    shutil.copy2(HERE.parent / 'scripts/slot-hwdb', script)
    script.chmod(0o755)
    compact_gconv(root)
    dedup = deduplicate_sdl(root)
    # The obsolete Bluetooth agent must not leave an executable service path.
    unit = root / 'usr/lib/systemd/system/bluetooth-agent.service'
    unit.unlink(missing_ok=True)
    unit.symlink_to('/dev/null')
    for link in unit.parent.glob('*.wants/bluetooth-agent.service'):
        link.unlink()
    if sharing is not None:
        result['file_sharing'] = sharing
    result.update(hwdb_bytes=database.stat().st_size, sdl_unpacked_deduplicated_bytes=dedup)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--boot-artifacts', type=Path,
                        help='Build-cache copy consumed by ROCKNIX factory-image generation')
    args = parser.parse_args()
    result = configure(args.root, boot_artifacts=args.boot_artifacts)
    print(json.dumps({k: v for k, v in result.items() if k != 'removed'}, indent=2))
