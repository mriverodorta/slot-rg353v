#!/usr/bin/env python3
"""Staged, identity-guarded RG353V internal installation from a running SD system."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import struct
import subprocess
import uuid
import zlib

MIB = 1024**2
DEFAULT_LAYOUT = {'boot_mib': 512, 'storage_mib': 512}
SUPPORTED_LAYOUTS = (DEFAULT_LAYOUT, {'boot_mib': 1024, 'storage_mib': 5120},
                     {'boot_mib': 2048, 'storage_mib': 5120})


def graphical_boot_arguments(args):
    """Keep kernel diagnostics on UART; reserve the LCD for the splash/UI."""
    result = [v for v in args if not re.fullmatch(r'console=tty[0-9]+(?:,.*)?', v)]
    if 'console=ttyS2,1500000' not in result:
        result.append('console=ttyS2,1500000')
    return result


def geometry(total, boot_mib=512, storage_mib=512):
    if total % 512 or total < 8 * 1024**3:
        raise ValueError('Unsupported internal capacity')
    if (type(boot_mib) is not int or type(storage_mib) is not int
            or {'boot_mib': boot_mib, 'storage_mib': storage_mib} not in SUPPORTED_LAYOUTS):
        raise ValueError('Unsupported boot/system partition layout')
    end = (total - 33 * 512) // MIB * MIB
    start = 16 * MIB
    boot, storage = boot_mib * MIB, storage_mib * MIB
    return {1: (start, boot), 2: (start + boot, storage),
            3: (start + boot + storage, end - start - boot - storage)}


def plan_geometry(plan):
    """Keep legacy receipts exact; only new explicit plans select the small layout."""
    if plan['schema'] == 1:
        if 'layout' in plan:
            raise ValueError('Legacy plans cannot override their partition layout')
        return geometry(plan['target']['bytes'], boot_mib=1024, storage_mib=5120)
    if plan['schema'] != 2 or plan.get('layout') not in SUPPORTED_LAYOUTS:
        raise ValueError('A schema 2 plan requires an explicit supported boot/system layout')
    return geometry(plan['target']['bytes'], **plan['layout'])


def gpt_regions(total, disk_guid, partition_guids, boot_mib=512, storage_mib=512):
    """Return the five bounded GPT writes; no external partitioning utility."""
    parts = geometry(total, boot_mib=boot_mib, storage_mib=storage_mib)
    last = total // 512 - 1
    entries = bytearray(128 * 128)
    for n, (start, size) in parts.items():
        kind = ('0fc63daf-8483-4772-8e79-3d69d8477de4' if n == 2 else
                'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')
        name = ('ROCKNIX', 'STORAGE', 'SLOT')[n-1].encode('utf-16le').ljust(72, b'\0')
        entries[(n-1)*128:n*128] = struct.pack('<16s16sQQQ72s', uuid.UUID(kind).bytes_le,
            uuid.UUID(partition_guids[str(n)]).bytes_le, start//512, (start+size)//512-1,
            4 if n == 1 else 0, name)

    def header(current, backup, table):
        raw = bytearray(struct.pack('<8sIIIIQQQQ16sQIII', b'EFI PART', 0x10000, 92,
            0, 0, current, backup, 34, last-33, uuid.UUID(disk_guid).bytes_le,
            table, 128, 128, zlib.crc32(entries)))
        struct.pack_into('<I', raw, 16, zlib.crc32(raw))
        return bytes(raw).ljust(512, b'\0')

    mbr = bytearray(512)
    mbr[446:462] = struct.pack('<B3sB3sII', 0, b'\x00\x02\x00', 0xee,
                             b'\xff\xff\xff', 1, min(last, 0xffffffff))
    mbr[510:512] = b'\x55\xaa'
    return [((last-32)*512, bytes(entries)), (last*512, header(last, 1, last-32)),
            (1024, bytes(entries)), (512, header(1, last, 2)), (0, bytes(mbr))]


def write_all(fd, data, offset):
    written = 0
    while written < len(data):
        count = os.pwrite(fd, data[written:], offset+written)
        if count <= 0:
            raise OSError('Short storage write')
        written += count


def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True).strip()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(MIB), b''):
            result.update(data)
    return result.hexdigest()


def atomic(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Installer:
    def __init__(self, path):
        self.plan_path = path.resolve()
        self.plan = json.loads(path.read_text())
        self.state_path = path.parent/'state.json'
        self.disk = Path('/dev/mmcblk0')
        self.parts = plan_geometry(self.plan)
        self.stage = Path('/run/slot-emmc-install')

    def state(self):
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else {'phase': 'new'}

    def save(self, phase, **extra):
        value = dict(self.state(), phase=phase, **extra)
        atomic(self.state_path, value)
        print(json.dumps({'phase': phase}), flush=True)

    def guard(self):
        p = self.plan
        assert p['schema'] in (1, 2) and p['mac_backup_confirmed'] is True
        assert b'anbernic,rg353v' in Path('/proc/device-tree/compatible').read_bytes()
        for name, expected, kind in [('mmcblk0', p['target'], 'MMC'), ('mmcblk1', p['source'], 'SD')]:
            block = Path('/sys/class/block')/name
            assert (block/'device/type').read_text().strip() == kind
            assert (block/'device/serial').read_text().strip() == expected['serial']
            assert int((block/'size').read_text())*512 == expected['bytes']
            major, minor = map(int, (block/'dev').read_text().split(':'))
            device = Path('/dev')/name
            assert stat.S_ISBLK(device.stat().st_mode)
            assert device.stat().st_rdev == os.makedev(major, minor)
        mounts = {v.split()[1]: v.split()[0] for v in Path('/proc/mounts').read_text().splitlines()}
        for mount, number in [('/flash', 1), ('/storage', 2), ('/storage/slotcontent', 3)]:
            assert mounts[mount] == '/dev/mmcblk1p'+str(number)
        assert not any(v.startswith('/dev/mmcblk0') for v in mounts.values())
        assert not list(Path('/sys/class/block/mmcblk0/holders').iterdir())
        assert 'cart=' in Path('/storage/slotcontent/Config/slot.state').read_text().splitlines()
        backup = json.loads(Path(p['backup']).read_text())
        assert backup['target_serial'] == p['target']['serial'] and backup['target_bytes'] == p['target']['bytes']
        for item in backup['extents']:
            assert (Path(p['backup']).parent/item['file']).stat().st_size == item['bytes']

    def device(self, n):
        return Path(str(self.disk)+'p'+str(n))

    def check_table(self):
        fd = os.open(self.disk, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            header = os.pread(fd, 512, 512)
            assert header[:8] == b'EFI PART'
            assert str(uuid.UUID(bytes_le=header[56:72])) == self.plan['disk_guid']
        finally:
            os.close(fd)
        for n, bounds in self.parts.items():
            p = Path('/sys/class/block')/self.device(n).name
            assert (int((p/'start').read_text())*512, int((p/'size').read_text())*512) == bounds

    def format(self):
        self.guard()
        assert self.state()['phase'] == 'new'
        assert not list(Path('/sys/class/block/mmcblk0').glob('mmcblk0p*'))
        self.save('formatting')
        fd = os.open(self.disk, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            regions = gpt_regions(self.plan['target']['bytes'], self.plan['disk_guid'],
                                  self.plan['partition_guids'], boot_mib=self.parts[1][1] // MIB,
                                  storage_mib=self.parts[2][1] // MIB)
            for offset, data in regions:
                write_all(fd, data, offset)
            os.fsync(fd)
            # Only read back the 34 KiB of partition metadata, not the full device.
            for offset, data in regions:
                assert os.pread(fd, len(data), offset) == data
        finally:
            os.close(fd)
        run('blockdev', '--rereadpt', self.disk)
        run('udevadm', 'settle', '--timeout=10')
        self.check_table()
        run('mkfs.vfat', '-F', '32', '-n', 'ROCKNIX', '-i', self.plan['boot_uuid'].replace('-', ''), self.device(1))
        run('mkfs.ext4', '-F', '-q', '-m', '1', '-L', 'STORAGE', '-U', self.plan['storage_uuid'],
            '-E', 'lazy_itable_init=0,lazy_journal_init=0', self.device(2))
        run('mkfs.exfat', '-L', 'SLOT', self.device(3))
        self.save('formatted', filesystems={str(n): run('blkid', '-p', '-o', 'export', self.device(n)) for n in self.parts})

    @contextlib.contextmanager
    def mounted(self):
        mounted = []
        try:
            for n, path, kind in [(1, self.stage/'boot', 'vfat'), (2, self.stage/'storage', 'ext4'),
                                  (3, self.stage/'storage/slotcontent', 'exfat')]:
                path.mkdir(parents=True, exist_ok=True)
                run('mount', '-t', kind, self.device(n), path); mounted.append(path)
            yield self.stage/'boot', self.stage/'storage', self.stage/'storage/slotcontent'
        finally:
            os.sync()
            for path in reversed(mounted):
                run('umount', path)

    def copy(self):
        self.guard(); self.check_table()
        assert self.state()['phase'] == 'formatted'
        self.save('copying')
        payload = Path(self.plan['payload'])
        meta = json.loads((payload.parent/'manifest.json').read_text())
        assert meta['target'] == {'arch': 'aarch64', 'device': 'rg353v'}
        for name, info in meta['files'].items():
            assert name in ('KERNEL', 'SYSTEM') or name.startswith(('device_trees/', 'overlays/'))
            assert '..' not in Path(name).parts and not Path(name).is_absolute()
            assert digest(payload/name) == info['sha256']
        excludes = ['slotcontent/***', 'slot-manager/***', 'slot-os-updates/***', '.slot-card*',
                    '.please_resize_me', '.cache/slot-bootloader-*', '.cache/slot-emmc-*',
                    '.config/slot-card-firstboot.py', '.config/slot-boot-progress-firstboot.py',
                    '.config/slot-content-device', '.config/slot-mount-content-same-disk',
                    '.config/system.d/storage-slotcontent.service.d/30-same-disk.conf']
        with self.mounted() as (boot, storage, content):
            run('rsync', '-rt', str(payload)+'/', str(boot)+'/')
            # This appliance's rsync omits ACL/xattr support. Preserve archive
            # metadata there and copy/verify extended attributes with Python.
            run('rsync', '-aHx', *['--exclude=/'+v for v in excludes], '/storage/', str(storage)+'/')
            for directory, dirs, names in os.walk(storage, followlinks=False):
                if Path(directory) == storage and 'slotcontent' in dirs:
                    dirs.remove('slotcontent')
                for target in [Path(directory), *(Path(directory)/n for n in dirs+names)]:
                    source = Path('/storage')/target.relative_to(storage)
                    for attr in os.listxattr(source, follow_symlinks=False):
                        value = os.getxattr(source, attr, follow_symlinks=False)
                        os.setxattr(target, attr, value, follow_symlinks=False)
                        assert os.getxattr(target, attr, follow_symlinks=False) == value
            run('rsync', '-rt', '--modify-window=1', '/storage/slotcontent/', str(content)+'/')
            args = [v for v in shlex.split(Path('/proc/cmdline').read_text())
                    if not v.startswith(('boot=', 'disk=', 'BOOT_IMAGE=', 'SYSTEM_IMAGE=', 'SLOT_OS_ID=', 'SLOT_BOOT_ASSETS='))]
            args = ['boot=UUID='+self.plan['boot_uuid'], 'disk=UUID='+self.plan['storage_uuid'], *args]
            args = graphical_boot_arguments(args)
            (boot/'extlinux').mkdir(exist_ok=True)
            (boot/'extlinux/extlinux.conf').write_text('LABEL SLOT-EMMC\n  LINUX /KERNEL\n  FDTDIR /device_trees\n  APPEND '+' '.join(args)+'\n')
            atomic(storage/'.slot-emmc-install.json', {'schema': 1, 'disk_guid': self.plan['disk_guid'],
                'partitions': self.parts, 'os_package': meta['id'], 'source_sd_serial': self.plan['source']['serial']})
            # Save files and preferences get a content check; ROMs get size/count checks.
            inventory = {}
            for source in Path('/storage/slotcontent').rglob('*'):
                if source.is_symlink():
                    raise ValueError('Unexpected content symlink')
                if not source.is_file():
                    continue
                name = source.relative_to('/storage/slotcontent'); target = content/name
                assert target.is_file() and source.stat().st_size == target.stat().st_size
                if name.parts[0] in ('Saves', 'States', 'Config'):
                    assert digest(source) == digest(target)
                inventory[str(name)] = source.stat().st_size
            assert not (storage/'slot-manager/state.json').exists()
        self.save('copied', content_inventory=inventory, os_package=meta['id'])

    def loader(self):
        self.guard(); self.check_table()
        assert self.state()['phase'] == 'copied'
        artifact = Path(self.plan['loader'])
        meta = json.loads(artifact.with_name('manifest.json').read_text())
        assert meta['emmc_select'] and meta['sd_clock_fix'] and meta['sd_offset_bytes'] == 32768
        data = artifact.read_bytes()
        assert len(data) == meta['bytes'] and hashlib.sha256(data).hexdigest() == meta['candidate_sha256']
        assert 32768+len(data) < self.parts[1][0]
        self.save('writing-loader')
        fd = os.open(self.disk, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            write_all(fd, data, 32768)
            os.fsync(fd)
        finally:
            os.close(fd)
        self.save('installed', loader_sha256=meta['candidate_sha256'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['inspect', 'format', 'copy', 'loader'])
    p.add_argument('--plan', type=Path, required=True)
    args = p.parse_args(); installer = Installer(args.plan)
    with (args.plan.parent/'install.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        installer.guard()
        if args.action == 'inspect':
            print(json.dumps({'geometry': installer.parts, 'state': installer.state()}, indent=2))
        else:
            getattr(installer, args.action)()


if __name__ == '__main__':
    main()
