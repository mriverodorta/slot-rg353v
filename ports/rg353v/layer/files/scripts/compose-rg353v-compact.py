#!/usr/bin/env python3
"""Compose a small factory image; finish the card layout on its first boot."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import uuid

spec = importlib.util.spec_from_file_location('layout', Path(__file__).with_name('rg353v-card-layout.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--provision-dir', type=Path, required=True)
    a = p.parse_args()
    if not a.input.is_file() or a.output.exists() or not all((a.provision_dir / n).is_dir() for n in ('storage', 'content')):
        raise ValueError('Expected regular input and a fresh output')
    parts = m.partitions(a.input)
    if set(parts) != {1, 2} or parts[1][0] != 16 * m.MIB:
        raise ValueError('Unexpected upstream partition layout')
    boot_start, boot_bytes, store_bytes = 16 * m.MIB, 1024 * m.MIB, 5120 * m.MIB
    geometry = {1: (boot_start, boot_bytes), 2: (boot_start + boot_bytes, store_bytes)}
    total = sum(geometry[2]) + m.MIB
    marker = {'schema': 2, 'phase': 'new', 'boot_start': boot_start, 'boot_bytes': boot_bytes,
              'initial_storage_bytes': store_bytes, 'storage_bytes': store_bytes,
              'disk_guid': str(uuid.uuid4()), 'storage_guid': str(uuid.uuid4()),
              'content_guid': str(uuid.uuid4())}
    with tempfile.TemporaryDirectory(dir=a.output.parent) as tmp:
        tmp = Path(tmp); boot = tmp / 'boot'; store = tmp / 'storage'
        boot.mkdir(); store.mkdir()
        with m.mounted(a.input, *parts[1], boot), m.mounted(a.input, *parts[2], store):
            boot_dev = m.run('findmnt', '-n', '-o', 'SOURCE', boot, capture=True).strip()
            store_dev = m.run('findmnt', '-n', '-o', 'SOURCE', store, capture=True).strip()
            boot_hex = uuid.uuid4().hex[:8].upper()
            boot_uuid = boot_hex[:4] + '-' + boot_hex[4:]
            store_uuid = str(uuid.uuid4())
            boot_tree = tmp / 'boot-tree'; shutil.copytree(boot, boot_tree)
            (boot_tree/'extlinux/extlinux.conf').write_text(
                'LABEL Slot\n  LINUX /KERNEL\n  FDT /device_trees/rk3566-anbernic-rg353v.dtb\n'
                f'  APPEND boot=UUID={boot_uuid} disk=UUID={store_uuid}'
                ' quiet console=ttyS2,1500000\n')
            tree = tmp / 'tree'; shutil.copytree(store, tree, symlinks=True)
            (tree / '.please_resize_me').unlink(missing_ok=True)
            m.copy_provision(a.provision_dir / 'storage', tree, m.PRIVATE_STORAGE)
            seed = tree / '.slot-card-seed'; seed.mkdir()
            m.copy_provision(a.provision_dir / 'content', seed, m.CONTENT_FOLDERS)
            (tree / '.slot-card-firstboot.json').write_text(json.dumps(marker, indent=2) + '\n')
            installer = tree / '.config/slot-card-firstboot.py'; installer.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'ports/rg353v/image/slot-card-firstboot.py', installer)
            installer.chmod(0o600)
            dropin = tree / '.config/system.d/storage-slotcontent.service.d/05-slot-card-firstboot.conf'
            dropin.parent.mkdir(parents=True, exist_ok=True)
            dropin.write_text('[Service]\nExecStartPre=/bin/sh -c "exec /usr/bin/python3 /storage/.config/slot-card-firstboot.py >> /storage/slot-card-firstboot.log 2>&1"\nTimeoutStartSec=600\n')
            monitor = Path(__file__).resolve().parents[1] / 'ports/rg353v/rocknix/slot-bootsplash/scripts/slot-boot-progress'
            monitor_text = monitor.read_text()
            if monitor_text.count('deadline=time.monotonic()+40;finished={}') != 1:
                raise ValueError('Boot monitor deadline changed; review first-boot override')
            (tree / '.config/slot-boot-progress-firstboot.py').write_text(monitor_text.replace(
                'deadline=time.monotonic()+40;finished={}', 'deadline=time.monotonic()+600;finished={}'))
            splash_dropin = tree / '.config/system.d/slot-boot-progress.service.d/05-slot-card-firstboot.conf'
            splash_dropin.parent.mkdir(parents=True, exist_ok=True)
            splash_dropin.write_text('[Service]\nExecStart=\nExecStart=/usr/bin/python3 /storage/.config/slot-boot-progress-firstboot.py\n')
            files = [tmp / 'boot.fat', tmp / 'storage.ext4']
            for file, (_, size) in zip(files, geometry.values()):
                with file.open('wb') as dst: dst.truncate(size)
            m.run('mkfs.vfat', '-F', '32', '-n', 'ROCKNIX', '-i', boot_uuid.replace('-', ''), files[0])
            for entry in boot_tree.iterdir(): m.run('mcopy', '-s', '-i', files[0], entry, '::/')
            m.run('mkfs.ext4', '-F', '-q', '-m', '1', '-L', 'STORAGE', '-U', store_uuid, '-d', tree, files[1])
        with a.output.open('xb') as dst: dst.truncate(total)
        m.sparse_copy(a.input, a.output, limit=boot_start)
        m.run('sgdisk', '--clear', '--disk-guid=' + marker['disk_guid'], a.output)
        for n, (start, size) in geometry.items():
            m.run('sgdisk', f'--new={n}:{start//512}:{(start+size)//512-1}',
                  f'--typecode={n}:' + ('0700' if n == 1 else '8300'),
                  '--partition-guid=' + str(n) + ':' + (str(uuid.uuid4()) if n == 1 else marker['storage_guid']), a.output)
        m.run('sgdisk', '--attributes=1:set:2', a.output)
        for file, (start, _) in zip(files, geometry.values()): m.sparse_copy(file, a.output, start)
        m.run('sgdisk', '--verify', a.output)
        if m.partitions(a.output) != geometry:
            raise ValueError('Compact image partition bounds disagree')
        a.output.chmod(0o600)
        a.output.with_suffix('.layout.json').write_text(json.dumps({'schema': 1, 'compact': True,
            'image_bytes': total, 'first_boot_plan': marker, 'private_provisioning': True}, indent=2) + '\n')
        print('Compact image composed:', a.output, total, 'bytes', flush=True)


if __name__ == '__main__': main()
