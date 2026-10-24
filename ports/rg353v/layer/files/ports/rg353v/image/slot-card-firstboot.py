#!/usr/bin/env python3
"""Finish a compact RG353V card once, before mounting Slot content."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
import uuid
import zlib

MIB = 1024**2
MARKER = '.slot-card-firstboot.json'
DROPIN = '.config/system.d/storage-slotcontent.service.d/05-slot-card-firstboot.conf'
SPLASH_DROPIN = '.config/system.d/slot-boot-progress.service.d/05-slot-card-firstboot.conf'
CONTENT = ('Games', 'BIOS', 'Labels', 'Wallpapers', 'Saves', 'States', 'Config')


def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True).strip()


def mount_source(target, mountinfo=Path('/proc/self/mountinfo')):
    def decode(value):
        return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)
    for line in mountinfo.read_text().splitlines():
        before, after = line.split(' - ', 1)
        fields, filesystem = before.split(), after.split()
        if decode(fields[4]) == str(target):
            return decode(filesystem[1])
    raise ValueError('Required filesystem is not mounted: ' + str(target))


def save(path, value):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def gpt_data(disk):
    with Path(disk).open('rb') as stream:
        total = stream.seek(0, os.SEEK_END)
        for header_lba in (1, total // 512 - 1):
            try:
                stream.seek(header_lba * 512); header = stream.read(512)
                if header[:8] != b'EFI PART':
                    raise ValueError('Missing GPT header')
                size, crc = struct.unpack_from('<II', header, 12)
                if not 92 <= size <= 512 or struct.unpack_from('<Q', header, 24)[0] != header_lba:
                    raise ValueError('Unsupported GPT header')
                checked = bytearray(header[:size]); checked[16:20] = b'\0' * 4
                if zlib.crc32(checked) != crc:
                    raise ValueError('Invalid GPT header')
                lba, count, entry_size, entries_crc = struct.unpack_from('<QIII', header, 72)
                if not 128 <= entry_size <= 512 or not 1 <= count <= 128 or lba * 512 + count * entry_size > total:
                    raise ValueError('Unsupported GPT entries')
                stream.seek(lba * 512); entries = stream.read(count * entry_size)
                if zlib.crc32(entries) != entries_crc:
                    raise ValueError('Invalid GPT table')
                return header, entries, entry_size, total
            except ValueError:
                continue
    raise ValueError('Neither primary nor end-of-card GPT is valid')


def table(disk):
    header, entries, entry_size, _ = gpt_data(disk)
    parts = {}
    for n in range(len(entries) // entry_size):
        row = entries[n * entry_size:(n + 1) * entry_size]
        if row[:16] != b'\0' * 16:
            start, end = struct.unpack_from('<QQ', row, 32)
            parts[n + 1] = {'start': start * 512, 'bytes': (end - start + 1) * 512,
                            'guid': str(uuid.UUID(bytes_le=row[16:32]))}
    return str(uuid.UUID(bytes_le=header[56:72])), parts


def expand_table(disk, desired, marker):
    header, original_entries, entry_size, total = gpt_data(disk)
    disk_guid, parts = table(disk); validate(disk_guid, parts, marker, desired)
    if entry_size != 128 or len(original_entries) != 128 * 128:
        raise ValueError('Installer expects the standard 128-entry GPT')
    entries = bytearray(original_entries)
    start, size = desired[2]
    struct.pack_into('<QQ', entries, entry_size + 32, start // 512, (start + size) // 512 - 1)
    start, size = desired[3]
    row = bytearray(128)
    row[:16] = uuid.UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7').bytes_le
    row[16:32] = uuid.UUID(marker['content_guid']).bytes_le
    struct.pack_into('<QQ', row, 32, start // 512, (start + size) // 512 - 1)
    name = 'slot'.encode('utf-16-le'); row[56:56+len(name)] = name
    entries[2*entry_size:3*entry_size] = row
    last = total // 512 - 1
    backup_entries = last - len(entries) // 512
    if (desired[3][0] + desired[3][1]) // 512 > backup_entries:
        raise ValueError('Content overlaps backup GPT')

    def make_header(current, other, entry_lba):
        result = bytearray(header)
        struct.pack_into('<QQ', result, 24, current, other)
        struct.pack_into('<QQ', result, 40, 34, backup_entries - 1)
        struct.pack_into('<Q', result, 72, entry_lba)
        struct.pack_into('<I', result, 88, zlib.crc32(entries))
        result[16:20] = b'\0' * 4
        struct.pack_into('<I', result, 16, zlib.crc32(result[:struct.unpack_from('<I', result, 12)[0]]))
        return result

    with Path(disk).open('r+b', buffering=0) as stream:
        mbr = bytearray(stream.read(512))
        protective = [446 + n*16 for n in range(4) if mbr[446+n*16+4] == 0xee]
        if mbr[510:512] != b'\x55\xaa' or len(protective) != 1:
            raise ValueError('Expected a protective MBR')
        struct.pack_into('<II', mbr, protective[0]+8, 1, min(last, 0xffffffff))
        # Publish the recovery copy durably before changing the primary table.
        stream.seek(backup_entries * 512); stream.write(entries)
        stream.seek(last * 512); stream.write(make_header(last, 1, backup_entries))
        os.fsync(stream.fileno())
        stream.seek(2 * 512); stream.write(entries)
        stream.seek(512); stream.write(make_header(1, last, 2))
        stream.seek(0); stream.write(mbr)
        os.fsync(stream.fileno())
    disk_guid, parts = table(disk); validate(disk_guid, parts, marker, desired)


def plan(total, marker):
    if marker.get('schema') not in (1, 2) or total % 512 or marker.get('phase') not in ('new', 'format_pending', 'formatted', 'complete'):
        raise ValueError('Unsupported provisioning plan')
    initial = marker.get('initial_storage_bytes', 0)
    if not 64 * MIB <= initial <= 8 * 1024**3 or initial % MIB:
        raise ValueError('Unexpected initial storage size')
    start, boot = marker['boot_start'], marker['boot_bytes']
    if marker['schema'] == 2:
        storage = marker.get('storage_bytes')
        if (start != 16*MIB or boot != 1024*MIB or type(storage) is not int
                or storage != 5120*MIB or initial > storage or total < 8*1024**3):
            raise ValueError('Unexpected 1 GiB / 5 GiB partition geometry')
        end = (total - 33*512) // MIB * MIB
        content_start = start + boot + storage
        return {1: (start, boot), 2: (start + boot, storage),
                3: (content_start, end - content_start)}
    games = marker['games_bytes'] // MIB * MIB
    if start != 16 * MIB or boot != 4096 * MIB or not MIB <= games <= 40_000_000_000:
        raise ValueError('Unexpected partition geometry')
    end = (total - 33 * 512) // MIB * MIB
    storage_start, content_start = start + boot, end - games
    if content_start - storage_start < 8 * 1024**3:
        raise ValueError('Card too small: requires 8 GiB Linux storage plus planned games space')
    return {1: (start, boot), 2: (storage_start, content_start - storage_start),
            3: (content_start, games)}


def validate(disk_guid, parts, marker, desired):
    if disk_guid != marker['disk_guid'] or set(parts) not in ({1, 2}, {1, 2, 3}):
        raise ValueError('Card identity or partition count differs from installer')
    if (parts[1]['start'], parts[1]['bytes']) != desired[1]:
        raise ValueError('Boot partition changed')
    p = parts[2]
    if p['guid'] != marker['storage_guid'] or p['start'] != desired[2][0]:
        raise ValueError('Storage identity/start changed')
    if p['bytes'] not in (marker['initial_storage_bytes'], desired[2][1]):
        raise ValueError('Unexpected storage size')
    if marker['phase'] in ('formatted', 'complete') and 3 not in parts:
        raise ValueError('Previously created content partition is missing')
    if 3 in parts:
        p = parts[3]
        if p['guid'] != marker['content_guid'] or (p['start'], p['bytes']) != desired[3]:
            raise ValueError('Existing content partition differs from installer')


class Partition(ctypes.Structure):
    _fields_ = [('start', ctypes.c_longlong), ('length', ctypes.c_longlong),
                ('pno', ctypes.c_int), ('devname', ctypes.c_char * 64),
                ('volname', ctypes.c_char * 64)]


class PartitionArgument(ctypes.Structure):
    _fields_ = [('op', ctypes.c_int), ('flags', ctypes.c_int), ('datalen', ctypes.c_int),
                ('data', ctypes.c_void_p)]


def kernel_partition(disk, number, geometry):
    name = disk.name + 'p' + str(number)
    sysfs = Path('/sys/class/block') / name
    present = sysfs.exists()
    if present and (int((sysfs / 'start').read_text()) * 512,
                    int((sysfs / 'size').read_text()) * 512) == geometry:
        pass
    else:
        part = Partition(geometry[0], geometry[1], number)
        arg = PartitionArgument(3 if present else 1, 0, ctypes.sizeof(part), ctypes.addressof(part))
        libc = ctypes.CDLL(None, use_errno=True)
        fd = os.open(disk, os.O_RDWR | os.O_CLOEXEC)
        try:
            if libc.ioctl(fd, 0x1269, ctypes.byref(arg)) != 0:
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error))
        finally:
            os.close(fd)
    for _ in range(50):
        if (sysfs / 'dev').exists():
            break
        time.sleep(0.1)
    major, minor = map(int, (sysfs / 'dev').read_text().strip().split(':'))
    device = Path('/dev') / name
    if not device.exists():
        os.mknod(device, stat.S_IFBLK | 0o600, os.makedev(major, minor))
    if not stat.S_ISBLK(device.stat().st_mode) or device.stat().st_rdev != os.makedev(major, minor):
        raise ValueError('Partition device identity mismatch')
    return device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', type=Path, default=Path('/storage'))
    parser.add_argument('--test-disk', type=Path)
    parser.add_argument('--stop-after-format', action='store_true')
    args = parser.parse_args()
    storage = args.storage.resolve(); marker_path = storage / MARKER
    if not marker_path.exists():
        return
    marker = json.loads(marker_path.read_text())
    missing = [name for name in ('blockdev', 'resize2fs', 'mkfs.exfat', 'blkid', 'mount', 'mountpoint', 'umount', 'sync') if not shutil.which(name)]
    if missing:
        raise ValueError('Required setup tools are unavailable: ' + ', '.join(missing))
    test = args.test_disk is not None
    if test:
        if os.environ.get('SLOT_CARD_FIRSTBOOT_TEST') != '1' or not re.fullmatch(r'/dev/loop\d+', str(args.test_disk)):
            raise ValueError('Tests require an explicitly selected loop device')
        disk = args.test_disk
    else:
        if args.stop_after_format or storage != Path('/storage'):
            raise ValueError('Unsupported production invocation')
        source = str(Path(mount_source(storage)).resolve())
        if not re.fullmatch(r'/dev/mmcblk\d+p2', source):
            raise ValueError('Storage is not an SD partition')
        disk = Path(source[:-2])
        flash = str(Path(mount_source(Path('/flash'))).resolve())
        if flash != str(disk) + 'p1' or (Path('/sys/class/block') / disk.name / 'device/type').read_text().strip() != 'SD':
            raise ValueError('Boot/storage do not belong to the same SD card')
        if b'anbernic,rg353v' not in Path('/proc/device-tree/compatible').read_bytes():
            raise ValueError('This installer is specific to RG353V')
    if not stat.S_ISBLK(disk.stat().st_mode) or run('blockdev', '--getss', disk) != '512':
        raise ValueError('Unsupported card device')
    source = str(Path(mount_source(storage)).resolve())
    if source != str(disk) + 'p2':
        raise ValueError('Mounted storage does not match the installer disk')
    desired = plan(int(run('blockdev', '--getsize64', disk)), marker)
    disk_guid, parts = table(disk); validate(disk_guid, parts, marker, desired)
    print('Preparing SD storage and exFAT games space (first boot only).', flush=True)
    expand_table(disk, desired, marker)
    p2 = kernel_partition(disk, 2, desired[2]); p3 = kernel_partition(disk, 3, desired[3])
    print('Card partitions ready; expanding Linux filesystem.', flush=True)
    run('resize2fs', p2)
    if marker['phase'] in ('new', 'format_pending'):
        marker['phase'] = 'format_pending'; save(marker_path, marker)
        run('mkfs.exfat', '-L', 'SLOT', p3)
        marker['phase'] = 'formatted'; save(marker_path, marker)
    print('Linux storage and exFAT filesystem ready.', flush=True)
    if marker['phase'] not in ('formatted', 'complete'):
        raise ValueError('Unsupported installer phase')
    if run('blkid', '-p', '-s', 'TYPE', '-o', 'value', p3) != 'exfat' or run('blkid', '-p', '-s', 'LABEL', '-o', 'value', p3) != 'SLOT':
        raise ValueError('Content filesystem changed; refusing to format it')
    if args.stop_after_format:
        raise RuntimeError('Intentional test interruption after formatting')
    target = storage / 'slotcontent'; target.mkdir(exist_ok=True)
    if subprocess.run(['mountpoint', '-q', str(target)]).returncode == 0:
        raise ValueError('Content is unexpectedly mounted before provisioning')
    seed = storage / '.slot-card-seed'
    print('Copying staged games, saves and settings.', flush=True)
    copied = 0
    run('mount', '-t', 'exfat', '-o', 'noatime,fmask=0022,dmask=0022', p3, target)
    try:
        for folder in CONTENT:
            original = seed / folder
            if not original.exists():
                continue
            if original.is_symlink() or not original.is_dir():
                raise ValueError('Invalid content seed')
            (target / folder).mkdir(exist_ok=True)
            for source_file in sorted(original.rglob('*')):
                if source_file.is_symlink():
                    raise ValueError('Seed symlinks are unsupported')
                destination = target / source_file.relative_to(seed)
                if source_file.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif source_file.is_file():
                    if destination.exists():
                        if not destination.is_file() or destination.stat().st_size != source_file.stat().st_size:
                            raise ValueError('Existing content differs; preserving it')
                        continue
                    temporary = destination.with_name('.' + destination.name + '.slot-seed-tmp')
                    with source_file.open('rb') as src, temporary.open('wb') as dst:
                        shutil.copyfileobj(src, dst, 1024**2)
                        dst.flush(); os.fsync(dst.fileno())
                    os.replace(temporary, destination)
                    copied += 1
                    if copied % 64 == 0:
                        print('Content files copied: ' + str(copied), flush=True)
        run('sync')
    finally:
        run('umount', target)
    marker.update(phase='complete', partitions={str(n): list(p) for n, p in desired.items()})
    save(marker_path, marker)
    shutil.rmtree(seed, ignore_errors=True)
    (storage / DROPIN).unlink(missing_ok=True)
    (storage / SPLASH_DROPIN).unlink(missing_ok=True)
    os.replace(marker_path, storage / '.slot-card-layout.json')
    run('sync')
    print('First-boot card setup complete. Subsequent boots skip this setup.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Card setup stopped safely: ' + str(error), file=sys.stderr, flush=True)
        raise
