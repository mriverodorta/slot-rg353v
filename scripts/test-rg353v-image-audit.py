#!/usr/bin/env python3
"""Image-namespace link handling and read-only inventory boundaries."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('audit',Path(__file__).with_name('audit-rg353v-image.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_absolute_image_links_never_resolve_against_host_libraries(self):
        folder=self.root/'usr/lib';folder.mkdir(parents=True)
        (folder/'libc.so.6').symlink_to('/usr/lib/libc-image.so')
        (folder/'libc-image.so').write_bytes(b'image')
        self.assertEqual(m.target(self.root,'usr/lib/libc.so.6'),folder/'libc-image.so')

    def test_escape_and_loop_are_rejected(self):
        (self.root/'escape').symlink_to('../outside')
        (self.root/'loop').symlink_to('loop')
        for name in ('escape','loop'):
            with self.subTest(name=name),self.assertRaises(ValueError):m.target(self.root,name)

    def test_inventory_keeps_firmware_out_of_userspace_and_changes_no_files(self):
        for name in ('usr/bin/slot','usr/lib/real.so','usr/lib/firmware/chip/fw.elf'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'original')
        (self.root/'usr/lib/libalias.so').symlink_to('/usr/lib/real.so')
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        def inspect(p):
            return {'class':64,'machine':183,'needed':['libalias.so','libabsent.so'] if p.name=='slot' else [],'soname':None,'runpath':[]}
        with patch.object(m,'elf',side_effect=inspect):result=m.inspect(self.root)
        self.assertEqual(result['userspace_elf_count'],2)
        self.assertEqual(result['missing_needed_names'],{'usr/bin/slot':['libabsent.so']})
        self.assertEqual(result['firmware_bytes_by_family'],{'chip':8})
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})


if __name__=='__main__':unittest.main()
