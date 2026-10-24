#!/usr/bin/env python3
"""Build a validated OS capsule inside the existing Linux image-tools container."""
import argparse
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('os_updater', str(ROOT / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-os-update'))
spec = importlib.util.spec_from_loader(loader.name, loader)
o = importlib.util.module_from_spec(spec)
loader.exec_module(o)
u = o.u


def copy_boot_payload(root, payload, archive, prefix):
    """Use the release's boot files when runtime SYSTEM copies were trimmed."""
    pending = {}
    for folder in ('device_trees', 'overlays'):
        source = root / 'usr/share/bootloader' / folder
        files = list(source.rglob('*')) if source.is_dir() else []
        if any(p.is_file() for p in files):
            for path in files:
                u.require(not path.is_symlink(), 'Boot files must not contain symlinks')
                if path.is_file():
                    name = folder + '/' + path.relative_to(source).as_posix()
                    pending[name] = path.read_bytes()
        else:
            base = prefix + '/3rdparty/bootloader/' + folder + '/'
            for member in archive.getmembers():
                if not member.name.startswith(base) or member.isdir():
                    continue
                name = folder + '/' + member.name.removeprefix(base)
                u.safe_path(name)
                u.require(member.isfile() and 0 <= member.size <= 4 << 20,
                          'Unsupported boot file in firmware archive')
                u.require(name not in pending, 'Duplicate boot file in firmware archive')
                with archive.extractfile(member) as stream:
                    pending[name] = stream.read()
    u.require(any(n.startswith('device_trees/') and n.endswith('.dtb') for n in pending),
              'Firmware has no device trees; preserve its 3rdparty/bootloader build inputs')
    u.require(sum(map(len, pending.values())) <= 32 << 20, 'Boot payload is oversized')
    for name, data in pending.items():
        if name.endswith(('.dtb', '.dtbo')):
            u.require(data[:4] == b'\xd0\x0d\xfe\xed', 'Invalid compiled device tree')
    for name, data in pending.items():
        path = payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def package(firmware, version, output):
    u.require(u.SAFE_ID.fullmatch(version) and len(version) <= 72, 'Invalid release id')
    u.require(not output.exists(), 'Output exists; choose a new release id/output')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='slot-os-package-') as temp:
        temp = Path(temp)
        payload = temp / 'payload'
        payload.mkdir()
        prefix = None
        with tarfile.open(firmware) as archive:
            for name in ('KERNEL', 'SYSTEM'):
                candidates = [m for m in archive if m.name.endswith('/target/' + name)]
                u.require(len(candidates) == 1 and candidates[0].isfile()
                          and 0 < candidates[0].size < o.MAX_OS_BYTES, 'Missing/ambiguous firmware ' + name)
                found = candidates[0].name.rsplit('/target/', 1)[0]
                u.safe_path(found)
                u.require(prefix is None or prefix == found, 'Firmware targets have different release roots')
                prefix = found
                with archive.extractfile(candidates[0]) as source, (payload / name).open('wb') as out:
                    shutil.copyfileobj(source, out)
        root = temp / 'system'
        # Module policy validates both included files and excluded files. Inspect
        # the complete filesystem; a partial extraction incorrectly reports
        # selected optional services as missing and cannot check exclusions.
        subprocess.run(['unsquashfs', '-no-xattrs', '-no-progress', '-processors', '2', '-d', str(root),
                        str(payload / 'SYSTEM')], check=True, stdout=subprocess.DEVNULL)
        info = o.inspect_system(root, payload / 'KERNEL')
        with tarfile.open(firmware) as archive:
            copy_boot_payload(root, payload, archive, prefix)
        inventory = {n: {'size': data['size'], 'sha256': data['sha256']} for n, data in u.files(payload).items()}
        u.require(all(o.payload_name(n) for n in inventory), 'Unsupported boot files')
        meta = {'schema': 1, 'kind': 'os', 'id': version,
                'target': {'device': 'rg353v', 'arch': 'aarch64'}, **info, 'files': inventory}
        candidate = temp / 'capsule.tar.gz'
        with tarfile.open(candidate, 'w:gz', compresslevel=1) as archive:
            raw = json.dumps(meta, sort_keys=True).encode()
            entry = tarfile.TarInfo('manifest.json')
            entry.size = len(raw)
            archive.addfile(entry, io.BytesIO(raw))
            for name in inventory:
                archive.add(payload / name, arcname='payload/' + name, recursive=False)
        partial = output.with_suffix('.partial')
        shutil.copyfile(candidate, partial)
        partial.replace(output)
        output.with_suffix(output.suffix + '.sha256').write_text(u.sha(output) + '  ' + output.name + '\n')
        print(json.dumps({'path': str(output), 'sha256': u.sha(output), 'bytes': output.stat().st_size, 'runtime': info['runtime']}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware', type=Path, required=True)
    p.add_argument('--id', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    package(args.firmware, args.id, args.output)
