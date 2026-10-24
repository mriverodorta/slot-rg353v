#!/usr/bin/env python3
"""Exercise linked-name migration, conflicts and interrupted recovery."""
import importlib.util
from pathlib import Path
import tempfile
import sys
sys.dont_write_bytecode = True
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('repair', Path(__file__).with_name('slot-fix-mac-names.py'))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class Migration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'content'
        self.root.mkdir()
        self.old = 'Zelda. '
        for p, value in {
            'Games/GBA/Zelda. .gba': b'rom',
            'Games/GBA/._Zelda. .gba': b'finder',
            'Labels/GBA/Zelda. .PNG': b'picture',
            'Labels/GBA/._Zelda. .PNG': b'finder-picture',
            'Saves/GBA/Zelda. .sav': b'progress',
            'Saves/GBA/Zelda. .srm': b'legacy-progress',
            'System/Cache/Labels/GBA/Zelda. .rgba': b'cache',
            'States/GBA/mgba/Zelda. /resume.state': b'resume',
            'States/GBA/mgba/Zelda. /2026-10-17_00-00-00.png': b'thumbnail',
            'States/GBA/gpsp/Zelda. /resume.state': b'other-core',
            'Config/slot.state': b'cart=Zelda. \r\ncart_platform=gba\r\nrecent=gba/Zelda. \r\nrecent=gb/Zelda. \r\nvolume=40\r\nperfect_overlay=1\r\n',
            'Config/selected_core.txt': b'# comment\nZelda. = mgba\nOther = gpsp\n',
            'Config/video_mode.ini': b'Zelda. = actual',
            'Labels/cart_shell.txt': b'Zelda. = solid\n',
            'Config/unrelated': b'unchanged',
        }.items():
            path = self.root/p
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        self.before = repair.fingerprint(self.root)
        self.backup = self.base/'backup'

    def plan(self):
        return repair.make_plan(self.root)

    def test_apply_references_and_exact_rollback(self):
        plan = self.plan()
        self.assertEqual(repair.fingerprint(self.root), self.before)
        self.assertEqual(len(plan['games']), 1)
        repair.apply(self.root, self.backup, plan)
        self.assertFalse((self.root/'Games/GBA/Zelda. .gba').exists())
        self.assertEqual((self.root/'Saves/GBA/Zelda.sav').read_bytes(), b'progress')
        self.assertEqual((self.root/'States/GBA/mgba/Zelda/resume.state').read_bytes(), b'resume')
        self.assertEqual((self.root/'States/GBA/gpsp/Zelda/resume.state').read_bytes(), b'other-core')
        self.assertEqual((self.root/'Labels/GBA/._Zelda.PNG').read_bytes(), b'finder-picture')
        state = (self.root/'Config/slot.state').read_bytes()
        self.assertIn(b'cart=Zelda\r\n', state)
        self.assertIn(b'recent=gba/Zelda\r\nrecent=gb/Zelda. \r\n', state)
        self.assertIn(b'perfect_overlay=1\r\n', state)
        self.assertEqual((self.root/'Config/video_mode.ini').read_bytes(), b'Zelda = actual')
        self.assertEqual(self.plan()['games'], [])
        repair.rollback(self.root, self.backup)
        self.assertEqual(repair.fingerprint(self.root), self.before)
        repair.rollback(self.root, self.backup)

    def test_shared_global_settings_migrate_once(self):
        p = self.root/'Games/GB/Zelda..gb'; p.parent.mkdir(parents=True); p.write_bytes(b'gb')
        repair.apply(self.root, self.backup, self.plan())
        self.assertEqual((self.root/'Config/selected_core.txt').read_text(), '# comment\nZelda = mgba\nOther = gpsp\n')

    def test_collision_before_any_mutation(self):
        p = self.root/'Saves/GBA/ZELDA.sav'; p.write_bytes(b'other-save')
        before = repair.fingerprint(self.root)
        with self.assertRaisesRegex(repair.RepairError, 'collision'):
            self.plan()
        self.assertEqual(repair.fingerprint(self.root), before)

    def test_case_unicode_and_extension_stem_collisions(self):
        for existing, unsafe in [('Cafe\u0301.gbc', 'Café .gb'), ('Test.gbc', 'test .gb')]:
            with self.subTest(existing=existing):
                folder = self.root/'Games/GB'; folder.mkdir(exist_ok=True)
                a, b = folder/existing, folder/unsafe
                a.write_bytes(b'1'); b.write_bytes(b'2')
                with self.assertRaisesRegex(repair.RepairError, 'collision'):
                    self.plan()
                a.unlink(); b.unlink()

    def test_config_collision(self):
        with (self.root/'Config/selected_core.txt').open('a') as stream:
            stream.write('Zelda = gpsp\n')
        with self.assertRaisesRegex(repair.RepairError, 'collision'):
            self.plan()

    def test_symlink_refused(self):
        p = self.root/'Saves/GBA/Zelda. .sav'
        outside = self.base/'outside'; outside.write_bytes(b'protected')
        p.unlink(); p.symlink_to(outside)
        with self.assertRaisesRegex(repair.RepairError, 'Symlink'):
            self.plan()
        self.assertEqual(outside.read_bytes(), b'protected')

    def test_failed_write_rolls_back_all_moves(self):
        real = repair.atomic_write
        def fail(path, data):
            if path == self.root/'Config/slot.state' and b'cart=Zelda\r' in data:
                raise OSError('injected storage failure')
            real(path, data)
        with patch.object(repair, 'atomic_write', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'injected'):
                repair.apply(self.root, self.backup, self.plan())
        self.assertEqual(repair.fingerprint(self.root), self.before)

    def test_interrupted_prepared_transaction_recovers(self):
        plan = self.plan()
        # Model power loss after two renames, before the first config write.
        self.backup.mkdir()
        plan['status'] = 'prepared'
        repair.save_journal(self.backup, plan)
        for move in plan['moves'][:2]:
            (self.root/move['from']).rename(self.root/move['to'])
        repair.rollback(self.root, self.backup)
        self.assertEqual(repair.fingerprint(self.root), self.before)

    def test_rollback_refuses_new_gameplay_without_partial_changes(self):
        repair.apply(self.root, self.backup, self.plan())
        (self.root/'Saves/GBA/Zelda.sav').write_bytes(b'new progress')
        before = repair.fingerprint(self.root)
        with self.assertRaisesRegex(repair.RepairError, 'changed'):
            repair.rollback(self.root, self.backup)
        self.assertEqual(repair.fingerprint(self.root), before)

    def test_space_only_key_already_trimmed_by_slot(self):
        folder = self.root/'Games/GB'; folder.mkdir()
        (folder/'Pokemon .gb').write_bytes(b'gb')
        p = self.root/'Config/cart_shell.txt'; p.write_text('Pokemon = solid\n')
        plan = self.plan()
        self.assertNotIn('Config/cart_shell.txt', [e['path'] for e in plan['edits']])

    def test_metadata_collision_is_not_overwritten(self):
        p = self.root/'Labels/GBA/._Zelda.PNG'
        p.write_bytes(b'existing metadata')
        with self.assertRaisesRegex(repair.RepairError, 'collision'):
            self.plan()
        self.assertEqual(p.read_bytes(), b'existing metadata')

    def test_backup_inside_root_refused(self):
        with self.assertRaisesRegex(repair.RepairError, 'outside'):
            repair.apply(self.root, self.root/'backup', self.plan())
        self.assertEqual(repair.fingerprint(self.root), self.before)


if __name__ == '__main__':
    unittest.main()
