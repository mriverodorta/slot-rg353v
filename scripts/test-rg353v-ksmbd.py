#!/usr/bin/env python3
"""SMB backend preparation and fail-before-delete migration contracts."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'ports/rg353v/rocknix'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


backend = load('ksmbd_prepare', PACKAGES / 'slot-rg353v/scripts/slot-ksmbd')
migration = load('ksmbd_migration', PACKAGES / 'slot-startup-profile/tools/configure-ksmbd.py')


class BackendTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.storage = self.root / 'storage'
        self.content = self.storage / 'slotcontent'
        self.content.mkdir(parents=True)
        self.runtime = self.root / 'run'
        self.template = self.root / 'template'
        self.template.write_bytes((PACKAGES / 'slot-rg353v/config/ksmbd.conf').read_bytes())

    def prepare(self):
        return backend.prepare(self.storage, self.runtime, self.template)

    def test_guest_configuration_is_private_and_does_not_touch_content(self):
        save = self.content / 'save.srm'
        save.write_bytes(b'current progress')
        path = self.prepare()
        self.assertEqual(path.read_bytes(), self.template.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        database = path.parent / 'ksmbdpwd.db'
        self.assertEqual(database.read_bytes(), b'')
        self.assertEqual(database.stat().st_mode & 0o777, 0o600)
        self.assertEqual(save.read_bytes(), b'current progress')
        self.prepare()
        self.assertEqual(save.read_bytes(), b'current progress')

    def test_usb_storage_ownership_blocks_preparation(self):
        active = self.runtime / 'slot-usb/active'
        active.parent.mkdir(parents=True)
        active.touch()
        with self.assertRaisesRegex(ValueError, 'USB storage'):
            self.prepare()
        self.assertFalse((self.runtime / 'ksmbd').exists())

    def test_content_symlink_is_rejected(self):
        self.content.rmdir()
        self.content.symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.prepare()

    def test_runtime_and_password_symlinks_are_rejected(self):
        self.runtime.mkdir()
        target = self.root / 'target'
        target.mkdir()
        (self.runtime / 'ksmbd').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.prepare()
        (self.runtime / 'ksmbd').unlink()
        self.prepare()
        password = self.runtime / 'ksmbd/ksmbdpwd.db'
        password.unlink()
        victim = self.root / 'victim'
        victim.write_text('preserve')
        password.symlink_to(victim)
        with self.assertRaises(OSError):
            self.prepare()
        self.assertEqual(victim.read_text(), 'preserve')

    def test_extra_share_or_changed_path_is_rejected(self):
        for text in ('[global]\n[Slot]\npath=/other\n',
                     '[global]\n[Slot]\npath=/storage/slotcontent\n[Extra]\n'):
            self.template.write_text(text)
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                self.prepare()


class PackageTests(unittest.TestCase):
    def test_installed_service_aliases_resolve_to_the_meson_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root/'image/usr/lib/ksmbd.tools'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o755)
            (root/'COPYING').write_text('package license fixture')
            result = self.package(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('ksmbd.mountd', 'ksmbd.control'):
                alias = root/'image/usr/sbin'/name
                self.assertTrue(alias.is_symlink())
                self.assertEqual(alias.resolve(strict=True), binary.resolve(strict=True))
                self.assertTrue(os.access(alias, os.X_OK))

    def test_missing_or_non_executable_binary_rejects_the_package(self):
        for present in (False, True):
            with self.subTest(present=present), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if present:
                    binary = root/'image/usr/lib/ksmbd.tools'
                    binary.parent.mkdir(parents=True)
                    binary.write_text('not executable')
                result = self.package(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'image/usr/sbin/ksmbd.mountd').is_symlink())

    @staticmethod
    def package(root):
        env = dict(os.environ, INSTALL=str(root/'image'), PKG_BUILD=str(root))
        return subprocess.run(['bash', '-c', 'source "$1"; post_makeinstall_target',
                               'ksmbd-package-test', str(PACKAGES/'ksmbd-tools/package.mk')],
                              env=env, capture_output=True, text=True, timeout=10)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'image'
        self.root.mkdir()
        marker = self.root / 'usr/sbin/ksmbd.mountd'
        marker.parent.mkdir(parents=True)
        marker.write_text('new backend')
        self.old = self.root / 'usr/sbin/smbd'
        self.old.write_bytes(b'reviewed legacy backend')
        self.policy = self.root.parent / 'policy.json'
        self.plan = {'schema': 1, 'backend': 'ksmbd', 'remove': {
            'usr/sbin/smbd': {'sha256': hashlib.sha256(self.old.read_bytes()).hexdigest(),
                              'bytes': self.old.stat().st_size}}}
        self.policy.write_text(json.dumps(self.plan))

    def prune(self, checker=lambda *_: None):
        return migration.prune(self.root, self.policy, checker)

    def test_removes_only_reviewed_payload_and_is_idempotent(self):
        license = self.root / 'usr/share/licenses/samba/COPYING'
        license.parent.mkdir(parents=True)
        license.write_text('retained license')
        result = self.prune()
        self.assertEqual(result['removed_files'], 1)
        self.assertFalse(self.old.exists())
        self.assertEqual(license.read_text(), 'retained license')
        self.assertEqual(self.prune()['removed_files'], 0)

    def test_missing_new_backend_preserves_old_backend(self):
        (self.root / 'usr/sbin/ksmbd.mountd').unlink()
        with self.assertRaisesRegex(ValueError, 'Install'):
            self.prune()
        self.assertTrue(self.old.exists())

    def test_changed_file_or_new_legacy_file_blocks_all_deletion(self):
        self.old.write_text('changed upstream')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.prune()
        self.assertTrue(self.old.exists())
        self.old.write_bytes(b'reviewed legacy backend')
        extra = self.root / 'usr/sbin/new-smbd'
        extra.write_text('unreviewed')
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            self.prune()
        self.assertTrue(self.old.exists())

    def test_retained_dependency_failure_preserves_old_backend(self):
        def missing_dependency(*_):
            raise ValueError('retained ELF needs Samba')
        with self.assertRaisesRegex(ValueError, 'retained ELF'):
            self.prune(missing_dependency)
        self.assertTrue(self.old.exists())

    def test_path_escape_blocks_all_deletion(self):
        self.plan['remove']['usr/../../outside'] = {'sha256': '0' * 64}
        self.policy.write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.prune()
        self.assertTrue(self.old.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
