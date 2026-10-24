#!/usr/bin/env python3
"""One-time, offline expansion of a clean RG353V image, running from RAM.

Never use this on an existing installation. The initial ext4 filesystem is a
fresh seed, not user storage. The original bootloader reserve is never written.
"""
import argparse
import ctypes
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


card = module('slot_card_setup', 'slot-card-firstboot.py')
emmc = module('slot_clean_geometry', 'slot-emmc-install.py')
MIB = 1024**2
# Installer-only seed; new installations use 512 MiB boot/system and remaining SLOT.
# LZ4 spends more space to reduce startup CPU work, so retain 16 MiB FAT margin.
INITIAL = {'boot_mib': 224, 'storage_mib': 224}
FINAL = dict(emmc.DEFAULT_LAYOUT)
PLAN_SCHEMA = 2
STARTER_MIB = 16 + INITIAL['boot_mib'] + INITIAL['storage_mib'] + 1
BOOT_PAYLOAD_LIMIT = (INITIAL['boot_mib'] - 16) * MIB
MARKER = 'slot-clean-firstboot.json'
INSTALL = '.slot-clean-install'
HOOKS = ('post-sysroot.sh', 'post-flash.sh', 'slot-clean-run.sh', MARKER, 'slot-clean-firstboot.py',
         'slot-card-firstboot.py', 'slot-emmc-install.py', 'slot-setup.py', 'slot-setup-ui.py',
         'slot-setup-font.json.gz', 'slot-setup-font.LICENSE.txt',
         'slot-modules.py', 'slot-module-install.py', 'slot-setup-access.py', 'slot-installer-loader.bin', 'slot-installer-loader.json', 'slot-setup-debug.py', 'slot-setup-debug.json')
CONTENT = ('Games/GB', 'Games/GBC', 'Games/GBA', 'BIOS', 'Labels', 'Wallpapers',
           'Saves', 'States', 'Config', 'Diagnostics')


def run(*args):
    return subprocess.check_output([str(v) for v in args], text=True).strip()


def check_plan(plan):
    legacy = plan.get('schema') == 1 and plan.get('final') == {'boot_mib': 1024, 'storage_mib': 5120}
    current = plan.get('schema') == PLAN_SCHEMA and plan.get('final') == FINAL
    if (not (legacy or current) or plan.get('kind') != 'slot-clean-firstboot'
            or plan.get('initial') != INITIAL):
        raise ValueError('Unsupported clean-image plan')
    for key in ('disk_guid', 'storage_uuid'):
        if str(uuid.UUID(plan[key])) != plan[key]:
            raise ValueError('Invalid filesystem/disk identity')
    if set(plan['partition_guids']) != {'1', '2', '3'}:
        raise ValueError('Invalid partition identities')
    guids = [str(uuid.UUID(v)) for v in plan['partition_guids'].values()]
    if len(set(guids + [plan['disk_guid'], plan['storage_uuid']])) != 5:
        raise ValueError('Duplicate clean-image identities')
    if not re.fullmatch(r'[0-9A-F]{4}-[0-9A-F]{4}', plan['boot_uuid']):
        raise ValueError('Invalid boot identity')


def initial_geometry():
    return {1: (16*MIB, INITIAL['boot_mib']*MIB),
            2: ((16+INITIAL['boot_mib'])*MIB, INITIAL['storage_mib']*MIB)}


def final_geometry(plan, total):
    check_plan(plan)
    return emmc.geometry(total, **plan['final'])


def validate(disk, plan, total, allow_small=False):
    check_plan(plan)
    if total % 512 or total < STARTER_MIB*MIB:
        raise ValueError('Device is smaller than the clean installer image')
    desired = final_geometry(plan, total) if total >= 8*1024**3 else None
    if desired is None and not allow_small:
        raise ValueError('SD setup requires at least 8 GiB of usable capacity')
    disk_guid, parts = card.table(disk)
    if disk_guid != plan['disk_guid'] or set(parts) not in ({1, 2}, {1, 2, 3}):
        raise ValueError('Unexpected disk or partition count')
    actual = {n: (p['start'], p['bytes']) for n, p in parts.items()}
    if actual not in (initial_geometry(), desired):
        raise ValueError('Disk differs from the initial or final clean layout')
    if any(p['guid'] != plan['partition_guids'][str(n)] for n, p in parts.items()):
        raise ValueError('Partition identity changed')
    return desired, desired is not None and actual == desired


def inventory(tree):
    result = {}
    for p in sorted(tree.rglob('*')):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            raise ValueError('Unsupported boot-tree entry')
        if p.is_file():
            result[str(p.relative_to(tree))] = {
                'bytes': p.stat().st_size, 'sha256': emmc.digest(p)}
    return result


def check_inventory(tree, expected):
    if inventory(tree) != expected:
        raise ValueError('Boot backup/restore verification failed')


def copy_region(disk, source, target, size):
    if target < source + size:
        raise ValueError('Relocation source and destination overlap')
    fd = os.open(disk, os.O_RDWR | os.O_CLOEXEC)
    try:
        for offset in range(0, size, MIB):
            data = os.pread(fd, min(MIB, size-offset), source+offset)
            if len(data) != min(MIB, size-offset):
                raise OSError('Short initial-storage read')
            emmc.write_all(fd, data, target+offset)
        os.fsync(fd)
    finally:
        os.close(fd)


def filesystem(device, kind, identity):
    field = 'UUID'
    if (run('blkid', '-p', '-s', 'TYPE', '-o', 'value', device) != kind
            or run('blkid', '-p', '-s', field, '-o', 'value', device) != identity):
        raise ValueError('Filesystem identity changed: ' + str(device))


def publish_partitions(disk, desired):
    # BLKPG_RESIZE_PARTITION cannot change an existing partition's start. Drop
    # only the unmounted starter p2 mapping before adding it at the new offset.
    node = Path('/sys/class/block') / (disk.name+'p2')
    if node.exists() and int((node/'start').read_text())*512 != desired[2][0]:
        actual = (int((node/'start').read_text())*512, int((node/'size').read_text())*512)
        if actual != initial_geometry()[2] or mounted_on_disk(disk):
            raise ValueError('Unexpected or mounted storage mapping')
        device = Path('/dev') / node.name
        major, minor = map(int, (node/'dev').read_text().split(':'))
        if device.exists() and (not stat.S_ISBLK(device.stat().st_mode)
                                or device.stat().st_rdev != os.makedev(major, minor)):
            raise ValueError('Unexpected starter storage node')
        part = card.Partition(0, 0, 2)
        arg = card.PartitionArgument(2, 0, ctypes.sizeof(part), ctypes.addressof(part))
        fd = os.open(disk, os.O_RDWR | os.O_CLOEXEC)
        try:
            if ctypes.CDLL(None, use_errno=True).ioctl(fd, 0x1269, ctypes.byref(arg)):
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error))
        finally:
            os.close(fd)
        # Loop devices may allocate a different minor after removal/addition;
        # devtmpfs normally handles this, scratch containers need it explicitly.
        if device.exists():
            device.unlink()
    return [card.kernel_partition(disk, n, desired[n]) for n in (1, 2, 3)]


def mounted_on_disk(disk):
    # A RAM-root chroot can hide mounts in PID 1's outer root. Include those,
    # deduplicated by mount ID, and match device numbers as well as path aliases.
    numbers = set()
    for node in Path('/sys/class/block').glob(disk.name+'*'):
        if re.fullmatch(re.escape(disk.name)+r'(?:p\d+)?',node.name):
            numbers.add((node/'dev').read_text().strip())
    records = {}
    for path in (Path('/proc/self/mountinfo'), Path('/proc/1/mountinfo')):
        for line in path.read_text().splitlines():
            before, after = line.split(' - ', 1)
            fields = before.split(); source = after.split()[1]
            if fields[2] in numbers or source.startswith(str(disk)+'p'):
                records.setdefault((fields[0],fields[2]),fields[4])
    return list(records.values())


def guard_source(disk, flash, plan, test=False, allow_small=False):
    """Verify the actual boot source before showing choices or changing disks."""
    if not stat.S_ISBLK(disk.stat().st_mode) or run('blockdev', '--getss', disk) != '512':
        raise ValueError('Unsupported block device')
    if test:
        if os.environ.get('SLOT_CLEAN_TEST') != '1' or not re.fullmatch(r'/dev/loop\d+', str(disk)):
            raise ValueError('Tests require an explicitly selected loop device')
    else:
        if not re.fullmatch(r'/dev/mmcblk\d+', str(disk)):
            raise ValueError('Only the booted MMC device may be expanded')
        if b'anbernic,rg353v' not in Path('/proc/device-tree/compatible').read_bytes():
            raise ValueError('This clean image is specific to RG353V')
        if Path('/proc/1/comm').read_text().strip() not in ('init', 'busybox'):
            raise ValueError('Setup must run before systemd/storage startup')
        # The normal root must be the copied SYSTEM, not a file on the FAT we resize.
        root_source = Path(card.mount_source(Path('/'))).name
        backing = Path('/sys/class/block') / root_source / 'loop/backing_file'
        if not backing.is_file() or backing.read_text().strip() != '/dev/SYSTEM':
            raise ValueError('Setup requires the one-time RAM-backed SYSTEM')
    if card.mount_source(flash) != str(disk) + 'p1':
        raise ValueError('Boot mount does not belong to the selected disk')
    if mounted_on_disk(disk) != [str(flash)]:
        raise ValueError('Another filesystem on this disk is mounted')
    total = int(run('blockdev', '--getsize64', disk))
    desired, relocated = validate(disk, plan, total, allow_small)
    filesystem(str(disk)+'p1', 'vfat', plan['boot_uuid'])
    filesystem(str(disk)+'p2', 'ext4', plan['storage_uuid'])
    return desired, relocated


def setup(disk, flash, work, plan, test=False, stop=None, progress=None, finalize=None):
    """Only the explicit loop-test path may run outside the early RAM root."""
    desired, relocated = guard_source(disk, flash, plan, test)
    total = int(run('blockdev', '--getsize64', disk))
    progress = progress or (lambda text, percent: None)
    progress('Preparing the SD card', 5)
    for tool in ('mkfs.vfat', 'mkfs.exfat', 'e2fsck', 'resize2fs', 'mount', 'umount'):
        if not shutil.which(tool):
            raise ValueError('Missing first-boot tool: ' + tool)
    # Keep a RAM copy before releasing the source boot mount. No games or private
    # provisioning are ever copied into a clean distribution image.
    snapshot = work / 'boot'; snapshot.mkdir()
    shutil.copytree(flash, snapshot, dirs_exist_ok=True)
    expected = inventory(snapshot)
    if sum(v['bytes'] for v in expected.values()) > BOOT_PAYLOAD_LIMIT:
        raise ValueError('Boot payload exceeds the reviewed clean-image budget')
    run('umount', flash)
    if mounted_on_disk(disk):
        raise ValueError('Disk is still mounted')
    if not relocated:
        progress('Preparing system storage', 20)
        print('Relocating the clean storage seed.', flush=True)
        initial = initial_geometry()[2]
        copy_region(disk, initial[0], desired[2][0], initial[1])
    fd = os.open(disk, os.O_RDWR | os.O_CLOEXEC)
    try:
        # Backup GPT is durable before primary GPT; the raw loader is untouched.
        for offset, data in emmc.gpt_regions(total, plan['disk_guid'], plan['partition_guids'], **plan['final']):
            emmc.write_all(fd, data, offset)
            os.fsync(fd)
    finally:
        os.close(fd)
    p1, p2, p3 = publish_partitions(disk, desired)
    validate(disk, plan, total)
    filesystem(p2, 'ext4', plan['storage_uuid'])
    result = subprocess.run(['e2fsck', '-f', '-p', str(p2)])
    if result.returncode not in (0, 1):
        raise ValueError('Relocated storage did not pass filesystem checks')
    run('resize2fs', p2)
    progress('Creating game storage', 45)
    storage = work / 'storage'; storage.mkdir()
    content = work / 'content'; content.mkdir()
    run('mount', p2, storage)
    try:
        journal = storage / INSTALL; journal.mkdir(exist_ok=True)
        durable = journal / 'boot'
        state_file = journal / 'state.json'
        state = json.loads(state_file.read_text()) if state_file.exists() else {'phase':'prepared','plan':plan,'boot_inventory':expected}
        if state.get('plan') != plan or state.get('phase') not in ('prepared','format_pending','formatted'):
            raise ValueError('Unexpected clean-install journal')
        if durable.exists():
            wanted=state.get('boot_inventory',expected)
            check_inventory(durable,wanted)
            if wanted!=expected:
                published=state.get('module_publication')
                changed={n for n in wanted.keys()|expected.keys() if wanted.get(n)!=expected.get(n)}
                pending={'SYSTEM.modules-new','SYSTEM.md5.modules-new','post-flash.sh.modules-new'}
                allowed=pending|{'SYSTEM','SYSTEM.md5','post-flash.sh'} if published else pending
                valid_hashes={wanted.get('SYSTEM',{}).get('sha256')}
                if published:valid_hashes.add(published['sha256'])
                if not changed<=allowed or expected.get('SYSTEM',{}).get('sha256') not in valid_hashes:
                    raise ValueError('Unexpected changed installer payload')
            expected=wanted
        else:
            shutil.copytree(snapshot,durable)
            run('sync');check_inventory(durable,expected)
        card.save(state_file, state)
        if stop == 'relocated':
            raise RuntimeError('Intentional test interruption after relocation')
        if state['phase'] in ('prepared', 'format_pending'):
            state['phase'] = 'format_pending'; card.save(state_file, state)
            run('mkfs.exfat', '-L', 'SLOT', p3)
            state['phase'] = 'formatted'; card.save(state_file, state)
        if run('blkid', '-p', '-s', 'TYPE', '-o', 'value', p3) != 'exfat':
            raise ValueError('Content filesystem changed')
        run('mount', '-t', 'exfat', p3, content)
        try:
            for name in CONTENT:
                (content / name).mkdir(parents=True, exist_ok=True)
            run('sync')
        finally:
            run('umount', content)
        if stop == 'formatted':
            raise RuntimeError('Intentional test interruption after content setup')
        print('Expanding boot storage and restoring the verified boot files.', flush=True)
        progress('Finishing the SD installation', 75)
        run('mkfs.vfat', '-F', '32', '-n', 'ROCKNIX', '-i', plan['boot_uuid'].replace('-', ''), p1)
        run('mount', p1, flash)
        try:
            # Publish extlinux last, after all its payloads are durable.
            for entry in durable.iterdir():
                if entry.name == 'extlinux':
                    continue
                dest = flash / entry.name
                shutil.copytree(entry, dest) if entry.is_dir() else shutil.copyfile(entry, dest)
            run('sync')
            shutil.copytree(durable / 'extlinux', flash / 'extlinux')
            run('sync')
            check_inventory(flash, expected)
            if finalize:
                card.save(storage / '.slot-clean-layout.json', {'schema':1,'phase':'complete','plan':plan,
                          'partitions':{str(n):list(g) for n,g in desired.items()}})
                finalize(storage,flash,journal,state)
            # Committing the marker first is safe only after all payload,
            # selected features and optional provisioning are durable.
            (flash / MARKER).unlink();run('sync')
            for name in HOOKS:
                if name==MARKER or (finalize and plan.get('sd_test') and name=='post-flash.sh'):continue
                (flash / name).unlink(missing_ok=True)
            (flash / 'slot-setup-debug.json').unlink(missing_ok=True)
            run('sync')
        finally:
            run('umount', flash)
        card.save(storage / '.slot-clean-layout.json', {
            'schema': 1, 'phase': 'complete', 'plan': plan,
            'partitions': {str(n): list(g) for n, g in desired.items()}})
        shutil.rmtree(journal)
        run('sync')
    finally:
        run('umount', storage)
    print('Clean first-boot setup complete; restart into normal Slot.', flush=True)
    progress('Ready to restart', 100)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--disk', type=Path, required=True)
    p.add_argument('--flash', type=Path, default=Path('/flash'))
    p.add_argument('--work', type=Path, default=Path('/run/slot-clean-work'))
    p.add_argument('--test', action='store_true')
    p.add_argument('--stop-after', choices=('relocated', 'formatted'))
    args = p.parse_args()
    if not args.test and (args.flash != Path('/flash') or args.work != Path('/run/slot-clean-work') or args.stop_after):
        raise ValueError('Unsupported production invocation')
    args.work.mkdir(mode=0o700)
    with (args.work / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        setup(args.disk, args.flash, args.work,
              json.loads((args.flash / MARKER).read_text()), args.test, args.stop_after)


if __name__ == '__main__':
    main()
