#!/usr/bin/env python3
"""Linux-only offline image compositor. Never opens a host SD-card device."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

MIB = 1024 * 1024
CONTENT_FOLDERS = ('Games', 'BIOS', 'Labels', 'Wallpapers', 'Saves', 'States', 'Config')
PRIVATE_STORAGE = ('.config/system/configs/system.cfg', '.config/NetworkManager',
                   '.cache/NetworkManager', '.cache/ssh', '.cache/slot-ssh',
                   '.cache/shadow', '.cache/services', '.ssh/authorized_keys',
                   '.config/slot-boot-profiler.enabled', '.configured')


def run(*args, capture=False):
    return subprocess.run([str(a) for a in args], check=True,
                          stdout=subprocess.PIPE if capture else None,
                          text=capture).stdout


def layout(card_bytes, boot_start, games_bytes=40_000_000_000):
    if card_bytes % 512 or boot_start < MIB or boot_start % MIB or games_bytes < MIB:
        raise ValueError('Card and boot offset must be sector/alignment compatible')
    end = (card_bytes - 33 * 512) // MIB * MIB
    games = games_bytes // MIB * MIB
    p1 = (boot_start, 4096 * MIB)
    p2_start = sum(p1)
    p3_start = end - games
    if p3_start - p2_start < 8 * 1024**3:
        raise ValueError('Less than 8 GiB left for Linux storage')
    return [p1, (p2_start, p3_start - p2_start), (p3_start, games)]


def partitions(image):
    text = run('parted', '-sm', image, 'unit', 'B', 'print', capture=True)
    return {int(row.split(':')[0]): (int(row.split(':')[1][:-1]), int(row.split(':')[3][:-1]))
            for row in text.splitlines() if row[:1].isdigit()}


@contextlib.contextmanager
def mounted(image, start, size, directory):
    loop = run('losetup', '--find', '--show', '--read-only', '--offset', start,
               '--sizelimit', size, image, capture=True).strip()
    try:
        kind = run('blkid', '-p', '-s', 'TYPE', '-o', 'value', loop, capture=True).strip()
        run('mount', '-o', 'ro,noload' if kind == 'ext4' else 'ro', loop, directory)
        try:
            yield Path(directory)
        finally:
            run('umount', directory)
    finally:
        run('losetup', '-d', loop)


def sparse_copy(source, target, offset=0, limit=None):
    remaining = limit if limit is not None else Path(source).stat().st_size
    with open(source, 'rb') as src, open(target, 'r+b') as dst:
        dst.seek(offset)
        while remaining:
            chunk = src.read(min(8 * MIB, remaining))
            if not chunk:
                raise RuntimeError('Unexpected source EOF')
            if chunk.count(0) != len(chunk):
                dst.write(chunk)
            else:
                dst.seek(len(chunk), os.SEEK_CUR)
            remaining -= len(chunk)


def image_uuid(image, number):
    text = run('sgdisk', '-i', number, image, capture=True)
    return next(line.split(': ', 1)[1] for line in text.splitlines()
                if line.startswith('Partition unique GUID:'))


def copy_provision(source, target, names):
    for name in names:
        original, destination = source / name, target / name
        if original.is_symlink():
            raise ValueError('Provisioning symlinks are unsupported')
        if original.is_dir():
            if any(p.is_symlink() for p in original.rglob('*')):
                raise ValueError('Provisioning symlinks are unsupported')
            shutil.copytree(original, destination, dirs_exist_ok=True)
        elif original.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--card-bytes', type=int, required=True)
    p.add_argument('--games-bytes', type=int, default=40_000_000_000)
    p.add_argument('--backup', type=Path, help='Optional private backup: copy Wi-Fi/SSH and Slot content')
    p.add_argument('--provision-dir', type=Path, help='Private snapshot with storage/ and content/ directories')
    args = p.parse_args()
    if not args.input.is_file() or args.output.exists():
        raise RuntimeError('Input missing or output already exists')
    if args.backup and args.provision_dir:
        raise ValueError('Choose a backup or a provisioning snapshot')
    if args.provision_dir and not all((args.provision_dir / name).is_dir() for name in ('storage', 'content')):
        raise ValueError('Missing private provisioning directories')
    src_parts = partitions(args.input)
    if set(src_parts) != {1, 2}:
        raise RuntimeError('Expected upstream two-partition GPT image')
    dest_parts = layout(args.card_bytes, src_parts[1][0], args.games_bytes)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        tmp = Path(tmp)
        boot, store = tmp / 'boot-tree', tmp / 'storage-tree'
        boot.mkdir(); store.mkdir()
        with mounted(args.input, *src_parts[1], boot), mounted(args.input, *src_parts[2], store):
            boot_dev = run('findmnt', '-n', '-o', 'SOURCE', boot, capture=True).strip()
            store_dev = run('findmnt', '-n', '-o', 'SOURCE', store, capture=True).strip()
            boot_uuid = run('blkid', '-p', '-s', 'UUID', '-o', 'value', boot_dev, capture=True).strip()
            store_uuid = run('blkid', '-p', '-s', 'UUID', '-o', 'value', store_dev, capture=True).strip()
            content = tmp / 'storage-copy'
            shutil.copytree(store, content, symlinks=True)
            (content / '.please_resize_me').unlink(missing_ok=True)
            (content / '.rg353v-layout.json').write_text(json.dumps({'schema':1, 'partitions':dest_parts}))
            if args.provision_dir:
                copy_provision(args.provision_dir / 'storage', content, PRIVATE_STORAGE)
            files = [tmp / 'boot.fat', tmp / 'storage.ext4', tmp / 'content.exfat']
            for f, (_, size) in zip(files, dest_parts):
                with f.open('wb') as out: out.truncate(size)
            run('mkfs.vfat', '-F', '32', '-n', 'ROCKNIX', '-i', boot_uuid.replace('-', ''), files[0])
            for entry in boot.iterdir():
                run('mcopy', '-s', '-i', files[0], entry, '::/')
            run('mkfs.ext4', '-F', '-q', '-L', 'STORAGE', '-U', store_uuid, '-d', content, files[1])
            run('mkfs.exfat', '-L', 'SLOT', files[2])
            if args.backup:
                backup_parts = partitions(args.backup)
                backup_mount = tmp / 'backup-storage'
                backup_mount.mkdir()
                with mounted(args.backup, *backup_parts[2], backup_mount):
                    for name in ('.cache/connman', '.cache/ssh', '.ssh'):
                        original = backup_mount / name
                        if original.is_dir():
                            shutil.copytree(original, content / name, dirs_exist_ok=True, symlinks=True)
                    services = content / '.cache/services'
                    services.mkdir(parents=True, exist_ok=True)
                    (services / 'sshd.conf').write_text('SSH_ARGS=""\n')
                    # Recreate storage with the optional private provisioning.
                    run('mkfs.ext4', '-F', '-q', '-L', 'STORAGE', '-U', store_uuid, '-d', content, files[1])
                    loop = run('losetup', '--find', '--show', files[2], capture=True).strip()
                    games_mount = tmp / 'content-mount'
                    games_mount.mkdir()
                    try:
                        run('mount', loop, games_mount)
                        try:
                            for name in CONTENT_FOLDERS:
                                original = backup_mount / 'slot-dev' / name
                                if original.is_dir():
                                    shutil.copytree(original, games_mount / name, dirs_exist_ok=True)
                        finally:
                            run('umount', games_mount)
                    finally:
                        run('losetup', '-d', loop)
            if args.provision_dir:
                games_mount = tmp / 'provision-mount'
                games_mount.mkdir()
                loop = run('losetup', '--find', '--show', files[2], capture=True).strip()
                try:
                    run('mount', loop, games_mount)
                    try:
                        copy_provision(args.provision_dir / 'content', games_mount, CONTENT_FOLDERS)
                    finally:
                        run('umount', games_mount)
                finally:
                    run('losetup', '-d', loop)
        with args.output.open('xb') as out: out.truncate(args.card_bytes)
        sparse_copy(args.input, args.output, limit=src_parts[1][0])
        run('sgdisk', '--clear', args.output)
        for i, (start, size) in enumerate(dest_parts, 1):
            command = ['sgdisk', f'--new={i}:{start//512}:{(start+size)//512-1}',
                       f'--typecode={i}:' + ('8300' if i == 2 else '0700'),
                       f'--change-name={i}:' + ['system', 'storage', 'slot'][i-1]]
            if i <= 2: command.append(f'--partition-guid={i}:{image_uuid(args.input,i)}')
            run(*command, args.output)
        run('sgdisk', '--attributes=1:set:2', args.output)
        for f, (start, _) in zip(files, dest_parts): sparse_copy(f, args.output, start)
        run('sgdisk', '--verify', args.output)
        if list(partitions(args.output).values()) != dest_parts:
            raise RuntimeError('Final partition bounds disagree')
        args.output.with_suffix('.layout.json').write_text(json.dumps({'schema':1,'card_bytes':args.card_bytes,
                 'partitions':dest_parts,'first_boot_resize':False,
                 'private_provisioning': bool(args.backup or args.provision_dir)},indent=2)+'\n')
        print('Offline image layout complete:', args.output)


if __name__ == '__main__': main()
