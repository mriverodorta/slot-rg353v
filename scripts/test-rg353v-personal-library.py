#!/usr/bin/env python3
"""Protect saves, archive conflicting versions, and refuse eMMC provisioning."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('library', Path(__file__).with_name('rg353v-personal-library.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private = self.root / 'private'
        self.content = self.private / 'content'
        self.content.mkdir(parents=True)
        self.source = self.root / 'source'
        self.source.mkdir()
        for name, value in [('PRIVATE', self.private), ('CONTENT', self.content)]:
            p = patch.object(m, name, value)
            p.start()
            self.addCleanup(p.stop)

    def save(self, value, timestamp):
        p = self.source / 'Saves/GBA/Zelda.sav'
        p.parent.mkdir(exist_ok=True, parents=True)
        p.write_bytes(value)
        os.utime(p, (timestamp, timestamp))
        return p

    def test_newer_progress_survives_older_backup_and_keeps_both(self):
        self.save(b'new progress', 200)
        m.merge(self.source, 'new')
        self.save(b'old progress', 100)
        m.merge(self.source, 'old')
        self.assertEqual((self.content / 'Saves/GBA/Zelda.sav').read_bytes(), b'new progress')
        history = list((self.private / 'history').rglob('*.sav'))
        self.assertEqual([p.read_bytes() for p in history], [b'old progress'])

    def test_live_device_save_wins_even_with_incorrect_device_clock(self):
        self.save(b'host progress', 200)
        m.merge(self.source, 'host')
        self.save(b'device progress', 100)
        m.merge(self.source, 'device', device=True)
        self.assertEqual((self.content / 'Saves/GBA/Zelda.sav').read_bytes(), b'device progress')
        self.assertEqual([p.read_bytes() for p in (self.private / 'history').rglob('*.sav')], [b'host progress'])

    def test_identical_imports_do_not_create_duplicate_save_versions(self):
        self.save(b'progress', 200)
        m.merge(self.source, 'one')
        m.merge(self.source, 'two')
        self.assertFalse((self.private / 'history').exists())
        self.assertEqual(len(list(self.content.rglob('*.sav'))), 1)

    def test_old_trailing_space_names_merge_into_correct_game(self):
        p = self.source / 'States/GBA/mgba/Zelda /resume.state'
        p.parent.mkdir(parents=True)
        p.write_bytes(b'state')
        m.merge(self.source, 'legacy')
        self.assertEqual((self.content / 'States/GBA/mgba/Zelda/resume.state').read_bytes(), b'state')

    def test_unsafe_archive_names_and_source_symlinks_are_rejected(self):
        for name in ['/Games/a.gba', 'Games/../../a.gba', 'System/slot', 'Saves/../a.sav']:
            with self.assertRaises(ValueError):
                m.relative(name)
        p = self.source / 'Games'
        p.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            m.merge(self.source, 'bad')

    def test_emmc_push_is_refused_before_pull_or_any_write(self):
        media = [{'type': 'MMC', 'device': 'mmcblk0', 'serial': 'owner'}] * 3
        with patch.object(m, 'inspect', return_value={'media': media}), patch.object(m, 'pull') as pull:
            with self.assertRaisesRegex(RuntimeError, 'eMMC requires explicit authorization'):
                m.push(object())
            pull.assert_not_called()
        self.assertNotIn('Config', m.TRANSFER)

    def test_push_authorization_requires_matching_serial_and_single_disk(self):
        media = [{'type': 'MMC', 'device': 'mmcblk0', 'serial': 'owner'}] * 3
        self.assertTrue(m.authorize_push(media, 'owner'))
        with self.assertRaises(RuntimeError):
            m.authorize_push(media, 'other')
        with self.assertRaises(RuntimeError):
            m.authorize_push([*media[:2], dict(media[2], device='mmcblk1')], 'owner')
        self.assertFalse(m.authorize_push([dict(v, type='SD') for v in media]))


class PortableInventory(unittest.TestCase):
    def test_progress_matches_game_source_and_settings_stay_internal(self):
        with tempfile.TemporaryDirectory() as d:
            system=Path(d)/'system';sd=Path(d)/'sd'
            for root in [system,sd]:
                for path,data in [('Games/GBA/Game.gba',b'rom'),('Saves/GBA/Game.sav',str(root).encode()),('States/GBA/mgba/Game/resume.state',str(root).encode()),('Config/slot.state',str(root).encode())]:
                    p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            def inventory(game):return dict(m.library_inventory(system,[system,sd],game,m.FOLDERS))
            self.assertEqual(inventory(True)['Saves/GBA/Game.sav'],system/'Saves/GBA/Game.sav')
            (system/'Games/GBA/Game.gba').unlink()
            selected=inventory(True)
            self.assertEqual(selected['Games/GBA/Game.gba'],sd/'Games/GBA/Game.gba')
            self.assertEqual(selected['Saves/GBA/Game.sav'],sd/'Saves/GBA/Game.sav')
            self.assertEqual(selected['States/GBA/mgba/Game/resume.state'],sd/'States/GBA/mgba/Game/resume.state')
            self.assertEqual(selected['Config/slot.state'],system/'Config/slot.state')
            self.assertEqual(inventory(False)['Saves/GBA/Game.sav'],system/'Saves/GBA/Game.sav')
            # A deliberately removed portable resume never resurrects its old eMMC copy.
            (sd/'States/GBA/mgba/Game/resume.state').unlink()
            self.assertNotIn('States/GBA/mgba/Game/resume.state',inventory(True))

if __name__ == '__main__':
    unittest.main()
