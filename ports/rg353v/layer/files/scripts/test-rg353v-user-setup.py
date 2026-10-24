#!/usr/bin/env python3
"""Linux fixture checks for boot gates; never touches live credentials or settings."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'ports/rg353v/rocknix/slot-startup-profile/src/slot-user-setup.c'

class Gates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / 'gate'
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(SOURCE), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.put('etc/os-release', 'VERSION=test\n')
        self.put('storage/.configured', '')
        (self.root / 'storage/.config/locale').mkdir(parents=True)
        self.put('storage/.cache/ld.so.cache', 'glibc-ld.so.cache1.1\0test')
        self.stamp = self.put('storage/.cache/ld.so.cache.osstamp',
                             str(int((self.root / 'etc/os-release').stat().st_mtime)) + '\n')
        self.factory = self.put('usr/cache/shadow', 'root:default:1:2:3:4:5:6:7\nuser:!:1:2:3:4:5:6:7\n')
        self.shadow = self.put('storage/.cache/shadow', 'root:custom:9:8:7:6:5:4:3\nuser:!:1:2:3:4:5:6:7\n')
        self.shadow.chmod(0)

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def ready(self, mode, expected):
        result = subprocess.run([self.binary, '--check', mode, self.root])
        self.assertEqual(result.returncode, 0 if expected else 1)

    def test_config_and_changed_os(self):
        self.ready('config', True)
        self.stamp.write_text('previous OS\n')
        self.ready('config', False)

    def test_missing_config_inputs(self):
        for name in ('storage/.configured', 'storage/.cache/ld.so.cache',
                     'storage/.cache/ld.so.cache.osstamp', 'etc/os-release'):
            p = self.root / name
            data = p.read_bytes()
            p.unlink()
            self.ready('config', False)
            p.write_bytes(data)
        (self.root / 'storage/.config/locale').rmdir()
        self.ready('config', False)

    @unittest.skipUnless(os.geteuid() == 0, 'cache fixture must model root ownership')
    def test_custom_password_and_no_writes(self):
        before = self.shadow.stat()
        data = self.shadow.read_bytes()
        self.ready('cache', True)
        self.assertEqual(data, self.shadow.read_bytes())
        self.assertEqual(before.st_mtime_ns, self.shadow.stat().st_mtime_ns)

    def test_invalid_shadow_and_permissions(self):
        for value in ('broken\n', self.shadow.read_text() + 'root:duplicate\n'):
            self.shadow.write_text(value)
            self.ready('cache', False)
        self.shadow.chmod(0o600)
        self.ready('cache', False)

    def test_new_factory_accounts(self):
        self.factory.write_text(self.factory.read_text() + 'newaccount:!:1:2:3:4:5:6:7\n')
        self.ready('cache', False)

    @unittest.skipUnless(os.geteuid() == 0, 'cache fixture must model root ownership')
    def test_missing_defaults_and_old_services_file(self):
        self.put('usr/cache/nested/default', 'factory')
        self.ready('cache', False)
        self.put('storage/.cache/nested/default', 'custom')
        self.ready('cache', True)
        self.put('storage/.cache/services', 'legacy')
        self.ready('cache', False)

if __name__ == '__main__':
    unittest.main()
