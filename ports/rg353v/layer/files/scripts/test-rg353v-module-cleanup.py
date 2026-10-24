#!/usr/bin/env python3
"""Installer retirement checks using disposable directories, no real disks."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('cleanup', str(ROOT / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-module-cleanup'))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.installed = {'kit': 'test-kit', 'selected': ['emulator-mgba']}
        self.layout = {'phase': 'complete', 'installed_from_sd': '7add725c-65f0-42cf-a6f3-33123599f60c'}
        self.mounts = dict(zip(('/flash', '/storage', '/storage/slotcontent'), ('/dev/mmcblk0p1', '/dev/mmcblk0p2', '/dev/mmcblk0p3')))
        self.save('.slot-clean-layout.json', self.layout)
        self.save('.slot-module-install-complete.json', self.installed)
        for name in ('.slot-modules', '.slot-module-install', '.slot-clean-install', '.slot-internal-install', 'slot-manager', 'slotcontent'):
            p = self.root / name; p.mkdir(); (p / 'retained').write_text('content')

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def test_sd_and_emmc_cleanup_retains_recovery_journal_and_personal_content(self):
        for kind in ('SD', 'MMC'):
            self.save('.slot-module-install-complete.json', self.installed)
            self.assertTrue(m.retire(self.root, self.installed, self.mounts, kind))
            self.assertFalse(m.retire(self.root, self.installed, self.mounts, kind))
            for name in ('.slot-modules', '.slot-module-install', '.slot-clean-install'):
                self.assertFalse((self.root / name).exists())
            for name in ('.slot-internal-install', 'slot-manager', 'slotcontent'):
                self.assertEqual((self.root / name / 'retained').read_text(), 'content')

    def test_internal_cleanup_requires_installer_origin(self):
        self.layout.pop('installed_from_sd'); self.save('.slot-clean-layout.json', self.layout)
        with self.assertRaises(KeyError): m.retire(self.root, self.installed, self.mounts, 'MMC')
        self.assertTrue((self.root / '.slot-module-install').exists())

    def test_split_disk_mounts_are_refused(self):
        for name in ('/storage', '/storage/slotcontent'):
            mounts = dict(self.mounts); mounts[name] = mounts[name].replace('mmcblk0', 'mmcblk1')
            with self.assertRaises(ValueError): m.retire(self.root, self.installed, mounts, 'MMC')

    def test_unconfirmed_selection_is_refused(self):
        with self.assertRaises(ValueError): m.retire(self.root, dict(self.installed, selected=[]), self.mounts, 'MMC')

    def test_unknown_device_is_refused(self):
        with self.assertRaises(ValueError): m.retire(self.root, self.installed, self.mounts, 'USB')

    def test_symlink_staging_is_refused_before_any_deletion(self):
        p = self.root / '.slot-module-install'; import shutil; shutil.rmtree(p); p.symlink_to(self.root / 'slotcontent')
        with self.assertRaises(ValueError): m.retire(self.root, self.installed, self.mounts, 'MMC')
        self.assertTrue((self.root / '.slot-modules').exists())
        self.assertEqual((self.root / 'slotcontent/retained').read_text(), 'content')


if __name__ == '__main__': unittest.main()
