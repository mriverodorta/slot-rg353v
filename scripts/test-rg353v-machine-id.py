#!/usr/bin/env python3
"""Persistent identity fast path and original-tool fallback, without host ID writes."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'ports/rg353v/rocknix/slot-startup-profile/src/slot-machine-id-setup.c'


class Identity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.binary = cls.root / 'setup'
        cls.identity = cls.root / 'machine-id'
        cls.backing = cls.root / 'persistent-id'
        cls.marker = cls.root / 'fallback-called'
        tool = cls.root / 'original-tool'
        tool.write_text('#!/bin/sh\ntouch "' + str(cls.marker) + '"\nexit 23\n')
        tool.chmod(0o755)
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-D_DARWIN_C_SOURCE',
                        '-DSLOT_MACHINE_ID_FILE="' + str(cls.identity) + '"',
                        '-DSLOT_MACHINE_ID_BACKING="' + str(cls.backing) + '"',
                        '-DSLOT_MACHINE_ID_TOOL="' + str(tool) + '"',
                        str(SOURCE), '-o', str(cls.binary)], check=True)

    def setUp(self):
        for path in (self.identity, self.backing, self.marker):
            path.unlink(missing_ok=True)

    def fixture(self, text):
        self.backing.write_bytes(text)
        self.identity.symlink_to(self.backing)

    def run_setup(self):
        return subprocess.run([str(self.binary)], capture_output=True).returncode

    def test_valid_persistent_id_is_unchanged_and_does_not_call_setup(self):
        text = b'0123456789abcdef0123456789abcdef\n'
        self.fixture(text)
        self.assertEqual(self.run_setup(), 0)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.backing.read_bytes(), text)

    def test_missing_or_malformed_identity_calls_original_and_propagates_status(self):
        cases = [b'', b'uninitialized\n', b'0' * 32 + b'\n', b'g' * 32 + b'\n',
                 b'a' * 31 + b'\n', b'a' * 32, b'a' * 32 + b'\nextra',
                 b'A' * 32 + b'\n', b'a' * 31 + b'\x00\n']
        self.assertEqual(self.run_setup(), 23)
        for text in cases:
            with self.subTest(text=text):
                self.setUp()
                self.fixture(text)
                self.assertEqual(self.run_setup(), 23)
                self.assertTrue(self.marker.exists())
                self.assertEqual(self.backing.read_bytes(), text)

    def test_equal_contents_on_different_inodes_do_not_skip_setup(self):
        text = b'f' * 32 + b'\n'
        self.backing.write_bytes(text)
        self.identity.write_bytes(text)
        self.assertEqual(self.run_setup(), 23)
        self.assertTrue(self.marker.exists())

    def test_read_only_check_never_initializes_identity(self):
        self.fixture(b'a' * 32 + b'\n')
        args = [str(self.binary), '--check', str(self.identity), str(self.backing)]
        self.assertEqual(subprocess.run(args).returncode, 0)
        self.backing.write_text('invalid\n')
        self.assertEqual(subprocess.run(args).returncode, 1)
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
