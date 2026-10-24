#!/usr/bin/env python3
"""Repair trailing spaces/dots in game stems together with their Slot data.

Default is a read-only plan. Stop Slot and file sharing before --apply.
"""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unicodedata


class RepairError(Exception):
    pass


def key(name):
    return unicodedata.normalize('NFC', name).casefold()


def contained(root, relative):
    path = root / relative
    if path == root or root not in path.parents or '..' in Path(relative).parts:
        raise RepairError('Invalid relative path: ' + str(relative))
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise RepairError('Symlink requires manual review: ' + str(part))
    return path


def fingerprint(path):
    if path.is_symlink():
        raise RepairError('Symlink requires manual review: ' + str(path))
    if path.is_file():
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return {'file': digest.hexdigest(), 'bytes': path.stat().st_size}
    if path.is_dir():
        return {'directory': {p.name: fingerprint(p) for p in sorted(path.iterdir())}}
    raise RepairError('Not a regular file or directory: ' + str(path))


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data):
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix='.slot-names-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def save_journal(backup, journal):
    atomic_write(backup / 'transaction.json', (json.dumps(journal, indent=2) + '\n').encode())


def game_names(root):
    games = []
    for platform, extensions in [('GB', ('.gb', '.gbc')), ('GBC', ('.gb', '.gbc')), ('GBA', ('.gba',))]:
        folder = contained(root, 'Games/' + platform)
        if folder.exists():
            for path in sorted(folder.iterdir()):
                if not path.name.startswith('.') and path.suffix.lower() in extensions and path.is_file():
                    games.append((platform, path))
    return games


def make_plan(root):
    games = game_names(root)
    changes = [(p, f, f.stem.rstrip(' .')) for p, f in games if f.stem.rstrip(' .') != f.stem]
    moves = {}

    def add(source, destination, metadata=False):
        if source == destination:
            return
        source = contained(root, source.relative_to(root))
        destination = contained(root, destination.relative_to(root))
        if not destination.name or (destination.name.startswith('.') and not metadata):
            raise RepairError('Empty/hidden destination: ' + str(destination))
        for sibling in destination.parent.iterdir():
            if sibling != source and key(sibling.name.rstrip(' .')) == key(destination.name):
                raise RepairError('Name collision: ' + str(destination))
        a, b = str(source.relative_to(root)), str(destination.relative_to(root))
        if any(key(b) == key(other) and a != src for src, other in moves.items()):
            raise RepairError('Two sources share a destination: ' + b)
        moves[a] = b

    for platform, rom, new in changes:
        if not new or new.startswith('.'):
            raise RepairError('Game name needs manual review: ' + rom.name)
        for other_platform, other in games:
            if other_platform == platform and other != rom and key(other.stem.rstrip(' .')) == key(new):
                raise RepairError('Game stem collision: ' + str(other))
        add(rom, rom.with_name(new + rom.suffix))
        folders = [rom.parent, root/'Labels'/platform, root/'Saves'/platform,
                   root/'System/Cache/Labels'/platform]
        for folder in folders:
            contained(root, folder.relative_to(root))
            if not folder.exists():
                continue
            for path in sorted(folder.iterdir()):
                name = path.name[2:] if path.name.startswith('._') else path.name
                candidate = Path(name)
                if candidate.suffix.lower() not in ('.gba', '.gb', '.gbc', '.png', '.sav', '.srm', '.rgba'):
                    continue
                if key(candidate.stem) == key(rom.stem):
                    prefix = '._' if path.name.startswith('._') else ''
                    # AppleDouble companions remain hidden metadata.
                    target = path.with_name(prefix + new + candidate.suffix)
                    add(path, target, metadata=bool(prefix))
        states = contained(root, Path('States')/platform)
        if states.exists():
            for core in sorted(states.iterdir()):
                contained(root, core.relative_to(root))
                if core.is_dir():
                    for path in sorted(core.iterdir()):
                        if key(path.name) == key(rom.stem):
                            add(path, path.with_name(new))

    edits = {}
    mapping = {(p.lower(), rom.stem): new for p, rom, new in changes}
    # Current and legacy state/config locations are supported.
    for relative in ('Config/slot.state', 'System/slot.state'):
        path = contained(root, relative)
        if not path.exists():
            continue
        before = path.read_bytes()
        lines = before.decode('utf-8').splitlines(keepends=True)
        platform = next((s.removeprefix('cart_platform=').strip() for s in lines if s.startswith('cart_platform=')), '')
        after = []
        for line in lines:
            body = line.rstrip('\r\n'); ending = line[len(body):]
            field, sep, value = body.partition('=')
            if sep and field == 'cart':
                matches = [new for (p, old), new in mapping.items() if old == value and (not platform or platform == p)]
                if len(set(matches)) > 1:
                    raise RepairError('Ambiguous active cartridge')
                if matches:
                    value = matches[0]
            elif sep and field == 'recent':
                p, slash, stem = value.partition('/')
                if slash:
                    value = p + '/' + mapping.get((p, stem), stem)
            after.append(field + sep + value + ending)
        if ''.join(after).encode() != before:
            edits[relative] = (before, ''.join(after).encode())

    stem_map = {}
    for _, rom, new in changes:
        old = unicodedata.normalize('NFC', rom.stem.strip())
        if old in stem_map and stem_map[old] != unicodedata.normalize('NFC', new.strip()):
            raise RepairError('Ambiguous global config key: ' + old)
        stem_map[old] = unicodedata.normalize('NFC', new.strip())
    unchanged = {unicodedata.normalize('NFC', f.stem.strip()) for p, f in games if (p.lower(), f.stem) not in mapping}
    config_files = ['Config/selected_core.txt', 'Config/video_mode.txt', 'Config/cart_shell.txt', 'Labels/cart_shell.txt',
                    'Config/selected_core.ini', 'Config/video_mode.ini', 'Config/cart_shell.ini', 'Labels/cart_shell.ini',
                    'System/selected_core.ini', 'System/video_mode.ini', 'System/cart_shell.ini']
    for relative in config_files:
        path = contained(root, relative)
        if not path.exists():
            continue
        before = path.read_bytes()
        lines = before.decode('utf-8').splitlines(keepends=True)
        def entry(line):
            if line.lstrip().startswith(('#', ';', '[')) or '=' not in line:
                return None
            return unicodedata.normalize('NFC', line.split('=', 1)[0].strip())
        keys = {entry(line) for line in lines}
        after = []
        for line in lines:
            old = entry(line)
            new = stem_map.get(old, old)
            if new != old:
                if new in keys:
                    raise RepairError('Config key collision: ' + relative + ': ' + new)
                if old in unchanged:
                    after.append(line if line.endswith('\n') else line + '\n')
                line = new + ' =' + line.split('=', 1)[1]
            after.append(line)
        if ''.join(after).encode() != before:
            edits[relative] = (before, ''.join(after).encode())
    return {'schema': 1, 'root': str(root), 'status': 'planned',
            'games': [{'platform': p, 'from': f.stem, 'to': new} for p, f, new in changes],
            'moves': [{'from': a, 'to': b, 'fingerprint': fingerprint(contained(root, a))} for a, b in sorted(moves.items())],
            'edits': [{'path': p, 'before': base64.b64encode(a).decode(), 'after': base64.b64encode(b).decode()} for p, (a, b) in sorted(edits.items())]}


def live_guard(root):
    if root != Path('/storage/slotcontent'):
        return
    if Path('/run/slot-usb/active').exists():
        raise RepairError('Exit USB storage first')
    for unit in ('slot-rg353v.service', 'smbd.service'):
        state = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, check=False).stdout.strip()
        if state not in ('inactive', 'failed', 'unknown'):
            raise RepairError('Stop ' + unit + ' first')
    state = contained(root, 'Config/slot.state')
    if state.exists() and any(s.startswith('cart=') and s != 'cart=' for s in state.read_text().splitlines()):
        raise RepairError('Eject the game before repairing names')


def rollback(root, backup):
    journal = json.loads((backup/'transaction.json').read_text())
    if journal['root'] != str(root) or journal['schema'] != 1:
        raise RepairError('Backup does not belong to this root')
    if journal['status'] == 'rolled-back':
        return journal
    # Preflight every path before undoing anything. Never overwrite later gameplay.
    for move in journal['moves']:
        a, b = (contained(root, move[k]) for k in ('from', 'to'))
        if a.exists() == b.exists() or fingerprint(a if a.exists() else b) != move['fingerprint']:
            raise RepairError('Files changed since repair; use backup for manual recovery: ' + move['to'])
    for edit in journal['edits']:
        data = contained(root, edit['path']).read_bytes()
        if data not in [base64.b64decode(edit[k]) for k in ('before', 'after')]:
            raise RepairError('Settings changed since repair; manual recovery required')
    for edit in reversed(journal['edits']):
        atomic_write(contained(root, edit['path']), base64.b64decode(edit['before']))
    for move in reversed(journal['moves']):
        a, b = (contained(root, move[k]) for k in ('from', 'to'))
        if b.exists():
            b.rename(a); sync_dir(a.parent)
    journal['status'] = 'rolled-back'
    save_journal(backup, journal)
    return journal


def apply(root, backup, journal):
    if root == backup or root in backup.parents:
        raise RepairError('Backup must be outside the content root')
    backup.mkdir(parents=True, exist_ok=False)
    backup.chmod(0o700)
    for move in journal['moves']:
        source = contained(root, move['from'])
        target = backup/'files'/move['from']
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        if fingerprint(target) != move['fingerprint']:
            raise RepairError('Backup verification failed: ' + move['from'])
    # Flush the backup before persisting the intent and touching originals.
    for path in (backup/'files').rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    os.sync() if hasattr(os, 'sync') else sync_dir(backup)
    journal['status'] = 'prepared'
    save_journal(backup, journal)
    sync_dir(backup.parent)
    try:
        for move in journal['moves']:
            source = contained(root, move['from']); target = contained(root, move['to'])
            if target.exists() or fingerprint(source) != move['fingerprint']:
                raise RepairError('Content changed during repair')
            source.rename(target); sync_dir(target.parent)
        for edit in journal['edits']:
            path = contained(root, edit['path'])
            if path.read_bytes() != base64.b64decode(edit['before']):
                raise RepairError('Settings changed during repair')
            atomic_write(path, base64.b64decode(edit['after']))
        journal['status'] = 'applied'
        save_journal(backup, journal)
    except Exception:
        rollback(root, backup)
        raise
    return journal


@contextlib.contextmanager
def locked(root):
    fd = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/storage/slotcontent'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', type=Path, metavar='BACKUP')
    parser.add_argument('--backup', type=Path, help='New backup directory outside content; required with --apply')
    args = parser.parse_args()
    root = args.root.absolute()
    if root != root.resolve() or not root.is_dir():
        parser.error('Root must be an existing directory with no symlink components')
    try:
        with locked(root):
            if args.apply or args.rollback:
                live_guard(root)
            if args.rollback:
                result = rollback(root, args.rollback.resolve())
            else:
                result = make_plan(root)
                if args.apply and result['games']:
                    if args.backup is None:
                        raise RepairError('--apply requires --backup')
                    result = apply(root, args.backup.resolve(), result)
            print(json.dumps(result, indent=2))
    except (OSError, ValueError, RepairError) as error:
        print('Repair refused: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
