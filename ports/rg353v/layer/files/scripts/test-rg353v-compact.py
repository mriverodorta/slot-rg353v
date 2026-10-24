#!/usr/bin/env python3
"""Test compact-card provisioning; integration touches only a disposable loop image."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

SCRIPT = Path(__file__).resolve().parents[1] / 'ports/rg353v/image/slot-card-firstboot.py'
spec = importlib.util.spec_from_file_location('firstboot', SCRIPT)
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)


def marker():
    return {'schema': 1, 'phase': 'new', 'boot_start': 16*f.MIB, 'boot_bytes': 4096*f.MIB,
            'initial_storage_bytes': 64*f.MIB, 'games_bytes': 4*1024**3,
            'disk_guid': str(uuid.uuid4()), 'storage_guid': str(uuid.uuid4()), 'content_guid': str(uuid.uuid4())}


class Geometry(unittest.TestCase):
    def test_mount_source_without_findmnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'mountinfo'
            path.write_text('7 1 179:98 / /storage rw - ext4 /dev/mmcblk1p2 rw\n8 1 7:2 / /with\\040space rw - ext4 /dev/loop2 rw\n')
            self.assertEqual(f.mount_source(Path('/storage'), path), '/dev/mmcblk1p2')
            self.assertEqual(f.mount_source(Path('/with space'), path), '/dev/loop2')
            with self.assertRaises(ValueError): f.mount_source(Path('/missing'), path)
    def test_new_layout_uses_remainder_and_fixed_system(self):
        for total in (8*1024**3, 16_000_000_000, 31_268_536_320, 60_492_349_440, 128_000_000_000):
            m = marker(); m.update(schema=2, boot_bytes=1024*f.MIB, storage_bytes=5120*f.MIB)
            m.pop('games_bytes')
            p = f.plan(total, m)
            self.assertEqual(p[1], (16*f.MIB, 1024*f.MIB))
            self.assertEqual(p[2], (1040*f.MIB, 5120*f.MIB))
            self.assertEqual(p[3][0], 6160*f.MIB)
            self.assertEqual(sum(p[3]), (total-33*512)//f.MIB*f.MIB)
            self.assertGreater(p[3][1], 0)
        for key, value in (('storage_bytes', 4096*f.MIB), ('boot_bytes', 2048*f.MIB), ('schema', 3)):
            bad = dict(m); bad[key] = value
            with self.assertRaises(ValueError): f.plan(64*1024**3, bad)
        with self.assertRaises(ValueError): f.plan(7*1024**3, m)

    def test_spare_layout(self):
        m = marker(); m['games_bytes'] = 40_000_000_000
        p = f.plan(60492349440, m)
        self.assertEqual(p[2], (4311744512, 16180576256))
        self.assertEqual(p[3], (20492320768, 39998980096))

    def test_small_card_rejected(self):
        m = marker(); m['games_bytes'] = 40_000_000_000
        with self.assertRaises(ValueError): f.plan(32*1024**3, m)

    def test_unexpected_geometry_rejected(self):
        m = marker(); m['boot_start'] = f.MIB
        with self.assertRaises(ValueError): f.plan(64*1024**3, m)

    def test_unknown_phase_rejected(self):
        m = marker(); m['phase'] = 'unknown'
        with self.assertRaises(ValueError): f.plan(64*1024**3, m)

    def test_identity_and_partition_guards(self):
        m = marker(); desired = f.plan(24*1024**3, m)
        parts = {1: {'start': desired[1][0], 'bytes': desired[1][1], 'guid': str(uuid.uuid4())},
                 2: {'start': desired[2][0], 'bytes': m['initial_storage_bytes'], 'guid': m['storage_guid']}}
        f.validate(m['disk_guid'], parts, m, desired)
        m['phase'] = 'formatted'
        with self.assertRaises(ValueError): f.validate(m['disk_guid'], parts, m, desired)
        m['phase'] = 'new'
        with self.assertRaises(ValueError): f.validate(str(uuid.uuid4()), parts, m, desired)
        for n, field, value in [(2, 'start', 0), (2, 'guid', str(uuid.uuid4())), (2, 'bytes', f.MIB)]:
            bad = {i: dict(v) for i, v in parts.items()}; bad[n][field] = value
            with self.assertRaises(ValueError): f.validate(m['disk_guid'], bad, m, desired)
        parts[3] = {'start': desired[3][0], 'bytes': desired[3][1], 'guid': str(uuid.uuid4())}
        with self.assertRaises(ValueError): f.validate(m['disk_guid'], parts, m, desired)


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0 and os.environ.get('SLOT_CARD_INTEGRATION') == '1', 'requires privileged scratch Linux container')
class Integration(unittest.TestCase):
    def test_online_growth_interrupted_seed_and_repeated_boot(self):
        self.exercise(marker(), 24*1024**3, 8*1024**3)

    def test_fixed_system_remainder_layout_and_resume(self):
        m = marker(); m.update(schema=2, boot_bytes=1024*f.MIB, storage_bytes=5120*f.MIB)
        m.pop('games_bytes')
        self.exercise(m, 31_268_536_320, int(4.5*1024**3))

    def exercise(self, m, total, minimum_storage):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root/'card.img'; seed = root/'seed'; seed.mkdir()
            start = m['boot_start'] + m['boot_bytes']; initial = start + m['initial_storage_bytes'] + f.MIB
            with image.open('wb') as out: out.truncate(initial)
            f.run('sgdisk', '--clear', '--disk-guid='+m['disk_guid'], '--new=1:32768:'+str(start//512-1),
                  '--new=2:'+str(start//512)+':'+str((start+m['initial_storage_bytes'])//512-1),
                  '--partition-guid=2:'+m['storage_guid'], image)
            (seed/f.MARKER).write_text(json.dumps(m))
            dropin = seed/f.DROPIN; dropin.parent.mkdir(parents=True); dropin.touch()
            splash_dropin = seed/f.SPLASH_DROPIN; splash_dropin.parent.mkdir(parents=True); splash_dropin.touch()
            game = seed/'.slot-card-seed/Games/GB/Probe.gb'; game.parent.mkdir(parents=True); game.write_bytes(b'private seed probe')
            fs = root/'storage.ext4'
            with fs.open('wb') as out: out.truncate(m['initial_storage_bytes'])
            f.run('mkfs.ext4', '-F', '-q', '-d', seed, fs)
            with image.open('r+b') as out, fs.open('rb') as src:
                out.seek(start)
                import shutil
                shutil.copyfileobj(src, out)
                out.truncate(total)
            disk = Path(f.run('losetup', '--find', '--show', '--partscan', image))
            storage = root/'mounted'; storage.mkdir(); games = root/'games'; games.mkdir()
            mounted = False
            nodes_before = {Path('/dev')/(disk.name+'p'+str(n)) for n in (1,2,3) if (Path('/dev')/(disk.name+'p'+str(n))).exists()}
            try:
                p2 = f.kernel_partition(disk, 2, (start, m['initial_storage_bytes']))
                f.run('mount', p2, storage); mounted = True
                env = dict(os.environ, SLOT_CARD_FIRSTBOOT_TEST='1')
                command = ['python3', str(SCRIPT), '--storage', str(storage), '--test-disk', str(disk)]
                result = subprocess.run(command+['--stop-after-format'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Intentional test interruption', result.stderr)
                self.assertEqual(json.loads((storage/f.MARKER).read_text())['phase'], 'formatted')
                # Simulate a damaged primary header; the durable backup must recover it.
                with disk.open('r+b', buffering=0) as raw:
                    raw.seek(512+16); current=raw.read(1)
                    raw.seek(512+16); raw.write(bytes([current[0] ^ 1])); os.fsync(raw.fileno())
                self.assertEqual(f.table(disk)[0], m['disk_guid'])
                p3 = Path(str(disk)+'p3')
                f.run('mount', p3, games); (games/'preserve.txt').write_text('preserve existing content'); f.run('umount', games)
                subprocess.run(command, env=env, check=True)
                self.assertFalse((storage/f.MARKER).exists()); self.assertFalse((storage/f.DROPIN).exists())
                self.assertFalse((storage/f.SPLASH_DROPIN).exists())
                self.assertFalse((storage/'.slot-card-seed').exists())
                self.assertEqual(json.loads((storage/'.slot-card-layout.json').read_text())['phase'], 'complete')
                self.assertGreater(os.statvfs(storage).f_blocks*os.statvfs(storage).f_frsize, minimum_storage)
                f.run('mount', '-o', 'ro', p3, games)
                self.assertEqual((games/'Games/GB/Probe.gb').read_bytes(), b'private seed probe')
                self.assertEqual((games/'preserve.txt').read_text(), 'preserve existing content')
                f.run('umount', games)
                subprocess.run(command, env=env, check=True)
                self.assertIn('No problems found', f.run('sgdisk', '--verify', disk))
            finally:
                subprocess.run(['umount', str(games)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if mounted: f.run('umount', storage)
                f.run('losetup', '-d', disk)
                for n in (1,2,3):
                    node=Path('/dev')/(disk.name+'p'+str(n))
                    if node not in nodes_before: node.unlink(missing_ok=True)


if __name__ == '__main__': unittest.main()
