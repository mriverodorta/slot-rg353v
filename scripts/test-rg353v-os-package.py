#!/usr/bin/env python3
"""Release boot metadata stays available after trimming runtime SYSTEM copies."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('os_package', ROOT/'scripts/package-rg353v-os.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
DTB = b'\xd0\x0d\xfe\xed' + b'compiled board data'


class BootPayload(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'root'
        self.payload = self.base/'payload'
        self.root.mkdir()
        self.payload.mkdir()

    def copy(self, entries):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            for name, data, kind in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        stream.seek(0)
        with tarfile.open(fileobj=stream) as archive:
            m.copy_boot_payload(self.root, self.payload, archive, 'Release')

    def entry(self, suffix='device_trees/rg353v.dtb', data=DTB):
        return ('Release/3rdparty/bootloader/'+suffix, data, tarfile.REGTYPE)

    def test_trimmed_system_uses_matching_release_boot_inputs(self):
        self.copy([self.entry(), self.entry('overlays/example.dtbo')])
        self.assertEqual((self.payload/'device_trees/rg353v.dtb').read_bytes(), DTB)
        self.assertEqual((self.payload/'overlays/example.dtbo').read_bytes(), DTB)
        self.assertFalse((self.root/'usr/share/bootloader').exists())

    def test_existing_runtime_trees_remain_supported(self):
        tree = self.root/'usr/share/bootloader/device_trees'
        tree.mkdir(parents=True)
        (tree/'rg353v.dtb').write_bytes(DTB)
        self.copy([])
        self.assertEqual((self.payload/'device_trees/rg353v.dtb').read_bytes(), DTB)

    def test_missing_or_different_release_trees_are_rejected(self):
        for entries in [[], [('Other/3rdparty/bootloader/device_trees/rg353v.dtb', DTB, tarfile.REGTYPE)]]:
            with self.assertRaises(m.u.UpdateError):
                self.copy(entries)
        self.assertEqual(list(self.payload.iterdir()), [])

    def test_path_escape_symlink_and_duplicate_are_rejected_before_writes(self):
        for entries in [[self.entry('device_trees/../../outside')],
                        [('Release/3rdparty/bootloader/device_trees/link.dtb', b'', tarfile.SYMTYPE)],
                        [self.entry(), self.entry()]]:
            with self.assertRaises(m.u.UpdateError):
                self.copy(entries)
            self.assertEqual(list(self.payload.iterdir()), [])
        self.assertFalse((self.base/'outside').exists())

    def test_invalid_compiled_tree_is_rejected_before_writes(self):
        with self.assertRaises(m.u.UpdateError):
            self.copy([self.entry(data=b'not a device tree')])
        self.assertEqual(list(self.payload.iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
