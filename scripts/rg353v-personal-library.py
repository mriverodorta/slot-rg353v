#!/usr/bin/env python3
"""Private host library: merge backups, pull before/after tests, and explicitly guarded provisioning.

This host maintenance tool is not part of a distributed firmware image.
"""
import argparse
import base64
import fcntl
import hashlib
from inspect import getsource
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.private-rg353v'
CONTENT = PRIVATE / 'content'
FOLDERS = ('Games', 'Saves', 'States', 'BIOS', 'Labels', 'Wallpapers', 'Screenshots', 'Config')
TRANSFER = FOLDERS[:-1]  # Installation settings are deliberately not pushed.


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in FOLDERS:
        raise ValueError('Unsafe content path: ' + name)
    # Old backups predate the macOS trailing-space filename correction.
    parts = [p.rstrip(' .') for p in path.parts]
    leaf = PurePosixPath(parts[-1])
    if leaf.suffix:
        parts[-1] = leaf.stem.rstrip(' .') + leaf.suffix
    if any(not p or p in ('.', '..') for p in parts):
        raise ValueError('Empty content path component')
    return Path(*parts)


def archive(path, rel):
    target = PRIVATE / 'history' / digest(path) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(path, target)
    return target


def merge(source, label, device=False):
    records = []
    pending_path = PRIVATE / 'pending-local-restore-v1.json'
    pending = json.loads(pending_path.read_text()).get('files', {}) if device and pending_path.exists() else {}
    for folder in FOLDERS:
        base = source / folder
        if not base.exists():
            continue
        if base.is_symlink():
            raise ValueError('Symlink source folder')
        for path in sorted(base.rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlink in library source')
            if not path.is_file() or path.name in ('.DS_Store', '.gitkeep') or path.name.startswith('._'):
                continue
            rel = relative(path.relative_to(source).as_posix())
            target = CONTENT / rel
            sha = digest(path)
            protected = str(rel) in pending
            expected = pending.get(str(rel))
            if protected and ((expected is None and not target.exists())
                              or (expected is not None and target.exists() and digest(target) == expected)):
                # A newly imported local restore is authoritative until explicitly
                # synced. Back up older device progress without undoing the import
                # or resurrecting a deliberately retired resume checkpoint.
                location = target if target.exists() and digest(target) == sha else archive(path, rel)
            elif target.exists() and digest(target) == sha:
                location = target
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                location = target
            elif (device and folder in ('Saves', 'States')) or path.stat().st_mtime > target.stat().st_mtime:
                archive(target, rel)
                shutil.copy2(path, target)
                location = target
            else:
                location = archive(path, rel)
            if digest(location) != sha:
                raise RuntimeError('Copied file verification failed')
            records.append({'source': str(path), 'path': str(rel), 'sha256': sha,
                            'stored': str(location.relative_to(PRIVATE)), 'bytes': path.stat().st_size})
    logs = PRIVATE / 'manifests'
    logs.mkdir(exist_ok=True)
    result = {'label': label, 'time': time.time(), 'files': records}
    (logs / (str(time.time_ns()) + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    return {'files_verified': len(records), 'bytes_verified': sum(p['bytes'] for p in records)}


GUARD = r'''
import os,json,sys,hashlib,tarfile,tempfile,shutil
from pathlib import Path, PurePosixPath
model=Path('/proc/device-tree/model').read_text().strip('\0')
assert model=='Anbernic RG353V', 'Unexpected device'
mounts={p[1]:p[0] for line in Path('/proc/mounts').read_text().splitlines() if len(p:=line.split())>=2}
media=[]
for target in ('/flash','/storage','/storage/slotcontent'):
 source=mounts[target];block=Path('/sys/class/block')/Path(os.path.realpath(source)).name
 device=block.resolve().parent if (block/'partition').exists() else block.resolve()
 media.append({'target':target,'source':source,'type':(device/'device/type').read_text().strip(),
 'device':device.name,'serial':(device/'device/serial').read_text().strip()})
assert 'cart=' in Path('/storage/slotcontent/Config/slot.state').read_text().splitlines(), 'Eject game first'
root=Path('/storage/slotcontent')
'''


def ssh_args(a):
    args = ['ssh', '-i', str(a.key), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(a.known_hosts),
            'root@' + a.host]
    if getattr(a, 'host_key_alias', None):
        args[-1:-1] = ['-o', 'HostKeyAlias=' + a.host_key_alias]
    return args


def command(code):
    data = base64.b64encode(code.encode()).decode()
    return 'python3 -B -c ' + shlex.quote('import base64;exec(base64.b64decode(' + repr(data) + '))')


def inspect(a):
    code = GUARD + "\nprint(json.dumps({'model':model,'media':media}))\n"
    return json.loads(subprocess.check_output(ssh_args(a) + [command(code)], timeout=30))


def library_inventory(system, roots, game_location, folders):
    """One canonical archive; progress follows the same ROM-source precedence as Slot."""
    games = {}
    candidates = []
    for library in roots:
        for folder in folders:
            if folder == 'Config' and library != system:
                continue
            base = library / folder
            if not base.exists():
                continue
            assert not base.is_symlink(), 'Symlink library folder'
            for path in sorted(base.rglob('*')):
                assert not path.is_symlink(), 'Symlink in device content'
                if not path.is_file() or path.name.startswith('._') or path.name == '.DS_Store':
                    continue
                rel = path.relative_to(library)
                candidates.append((library, path, rel))
                if folder == 'Games' and len(rel.parts) == 3 and path.suffix.lower() in ('.gb', '.gbc', '.gba'):
                    games.setdefault((rel.parts[1], path.stem.lower()), library)
    result = {}
    for library, path, rel in candidates:
        folder = rel.parts[0]
        if folder in ('Saves', 'States'):
            key = ((rel.parts[1], path.stem.lower()) if folder == 'Saves' and len(rel.parts) == 3
                   else (rel.parts[1], rel.parts[3].lower()) if folder == 'States' and len(rel.parts) >= 5 else None)
            chosen = games.get(key) if game_location else system
            if chosen is not None and library != chosen:
                continue
            if game_location and chosen is None and library == system:
                # Old internal checkpoints for removed SD games are not the
                # active progress and must not replace the canonical SD backup.
                continue
        result.setdefault(str(rel), path)
    return sorted(result.items())


def pull(a):
    identity = inspect(a)
    code = GUARD + '\n' + getsource(library_inventory) + '\nfolders=' + repr(FOLDERS) + r'''
roots=[root]
policy=root/'Config/save-location'
game_location=policy.exists() and policy.read_text().strip()=='game'
for line in Path('/run/slot-sd-library/roots').read_text().splitlines() if Path('/run/slot-sd-library/roots').exists() else []:
 if line not in ('/run/slot-sd-library/TF1','/run/slot-sd-library/TF2') or line not in mounts:continue
 source=mounts[line];node=Path('/sys/class/block')/Path(source).name
 disk=node.resolve().parent if (node/'partition').exists() else node.resolve()
 assert (disk/'device/type').read_text().strip()=='SD', 'Secondary library is not an SD card'
 assert disk.name not in {m['device'] for m in media}, 'Secondary library overlaps system disk'
 rows=[r.split() for r in Path('/proc/mounts').read_text().splitlines() if r.split()[1]==line]
 assert len(rows)==1 and rows[0][2]=='exfat', 'Secondary mount changed'
 roots.append(Path(line))
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tar:
 for rel,path in library_inventory(root, roots, game_location, folders):
  tar.add(path,arcname=rel,recursive=False)
'''
    # A failed SSH transfer is never merged into the canonical library.
    with tempfile.TemporaryDirectory(dir=PRIVATE, prefix='pull-') as tmp:
        tmp = Path(tmp)
        with (tmp / 'content.tar').open('wb') as f:
            subprocess.run(ssh_args(a) + [command(code)], stdout=f, check=True, timeout=1200)
        incoming = tmp / 'incoming'
        incoming.mkdir()
        total = 0
        with tarfile.open(tmp / 'content.tar') as tar:
            for entry in tar:
                if not entry.isfile() or entry.size > 512 * 1024**2:
                    raise ValueError('Unsupported device archive entry')
                total += entry.size
                if total > 32 * 1024**3:
                    raise ValueError('Transfer exceeds bound')
                rel = relative(entry.name)
                target = incoming / rel
                if target.exists():
                    raise ValueError('Duplicate device archive entry')
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(entry) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                os.utime(target, (entry.mtime, entry.mtime))
        result = merge(incoming, 'device:' + a.host + ':' + json.dumps(identity), device=True)
    return dict(result, device=identity)


def authorize_push(media, emmc_serial=None):
    if len(media) != 3 or len({m['device'] for m in media}) != 1:
        raise RuntimeError('Push refused: boot, system and content must share one disk')
    if all(m['type'] == 'SD' for m in media) and emmc_serial is None:
        return False
    if (emmc_serial and all(m['type'] == 'MMC' for m in media)
            and all(m['serial'] == emmc_serial for m in media)):
        return True
    raise RuntimeError('Push refused: eMMC requires explicit authorization for its exact serial')


def push(a):
    identity = inspect(a)
    emmc_serial = getattr(a, 'allow_emmc_serial', None)
    emmc = authorize_push(identity['media'], emmc_serial)
    # Preserve current device progress before any controlled provisioning.
    pull(a)
    code = GUARD + '\n' + getsource(authorize_push) + '\nallowed=' + repr(TRANSFER) + '\nemmc_serial=' + repr(emmc_serial) + r'''
emmc = authorize_push(media, emmc_serial)
count=0
# Stage on the verified content filesystem, not the deliberately small system
# partition. Keep the complete incoming archive isolated until it is validated.
assert root.is_mount() and not root.is_symlink()
with tempfile.TemporaryDirectory(dir=root,prefix='.library-push-') as tmp:
 tmp=Path(tmp);items=[];total=0
 with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as tar:
  for entry in tar:
   rel=PurePosixPath(entry.name)
   assert entry.isfile() and not rel.is_absolute() and '..' not in rel.parts and rel.parts[0] in allowed
   assert entry.size<=512*1024**2
   total+=entry.size;assert total<=32*1024**3
   assert shutil.disk_usage(root).free >= entry.size + 64*1024**2, 'Insufficient content staging space'
   target=tmp/str(rel);target.parent.mkdir(parents=True,exist_ok=True)
   assert not target.exists(), 'Duplicate entry'
   with tar.extractfile(entry) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
   items.append((rel,target))
 assert 'cart=' in (root/'Config/slot.state').read_text().splitlines(), 'Game started during transfer'
 authorize_push(media, emmc_serial)
 for rel,source in items:
  target=root/str(rel)
  assert not any(p.is_symlink() for p in [target,*target.parents]), 'Destination symlink'
  if target.is_file() and hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest():continue
  target.parent.mkdir(parents=True,exist_ok=True)
  fd,name=tempfile.mkstemp(prefix='.library-',dir=target.parent)
  try:
   with os.fdopen(fd,'wb') as dst,source.open('rb') as src:
    shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
   assert hashlib.sha256(Path(name).read_bytes()).digest()==hashlib.sha256(source.read_bytes()).digest()
   os.replace(name,target);count+=1
  finally:
   if Path(name).exists():Path(name).unlink()
os.sync()
print(json.dumps({'files_updated':count,'emmc_writes':emmc,'settings_preserved':True}))
'''
    with tempfile.TemporaryFile(dir=PRIVATE) as stream:
        with tarfile.open(fileobj=stream, mode='w') as tar:
            for folder in TRANSFER:
                for path in sorted((CONTENT / folder).rglob('*')):
                    if path.is_symlink():
                        raise ValueError('Library symlink')
                    if path.is_file() and path.name not in ('.DS_Store', '.gitkeep') and not path.name.startswith('._'):
                        tar.add(path, arcname=str(path.relative_to(CONTENT)), recursive=False)
        stream.seek(0)
        result = subprocess.check_output(ssh_args(a) + [command(code)], stdin=stream, timeout=1200)
    return json.loads(result)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('status', 'import', 'pull', 'push'))
    p.add_argument('--source', type=Path)
    p.add_argument('--allow-emmc-serial', help='Explicitly authorize content provisioning to this exact eMMC serial; default remains SD only')
    p.add_argument('--host', help='Handheld IP address; required for remote actions')
    p.add_argument('--host-key-alias', help='Use an already verified device identity, e.g. for USB SSH')
    p.add_argument('--key', type=Path, default=Path.home() / '.ssh/slot_rg353v_ed25519')
    p.add_argument('--known-hosts', type=Path, default=PRIVATE / 'known_hosts')
    a = p.parse_args()
    if a.action != 'import' and not a.host:
        p.error('--host is required for status, pull and push')
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    PRIVATE.chmod(0o700)
    lock = (PRIVATE / '.sync.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    CONTENT.mkdir(mode=0o700, exist_ok=True)
    if a.action == 'import':
        if not a.source or not a.source.is_dir():
            p.error('import requires --source containing Games/Saves/States/etc.')
        if a.source.resolve() == CONTENT.resolve() or PRIVATE.resolve() in a.source.resolve().parents:
            p.error('Source must be outside the canonical library')
        result = merge(a.source.resolve(), str(a.source))
    elif a.action == 'pull':
        result = pull(a)
    elif a.action == 'push':
        result = push(a)
    else:
        files = [f for f in CONTENT.rglob('*') if f.is_file()]
        result = {'library': str(CONTENT), 'files': len(files), 'bytes': sum(f.stat().st_size for f in files),
                  'roms': sum(f.suffix.lower() in ('.gb', '.gbc', '.gba') for f in files)}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
