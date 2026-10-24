#!/usr/bin/env python3
"""Fail closed before removing image files; preserve native graphics and UTF-8 tools."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'ports/rg353v/rocknix/slot-startup-profile'
spec=importlib.util.spec_from_file_location('image_prune',PKG/'tools/configure-image-prune.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Prune(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'image';self.meta=self.root/'usr/share/slot'
        (self.meta/'hardware').mkdir(parents=True)
        self.factory={'device':'rg353v','userspace_profile':'rg353v-lean-v1','build_profile':'normal'}
        (self.meta/'os-profile.json').write_text(json.dumps(self.factory))
        protected=self.root/'usr/lib/libEGL.so.1';protected.parent.mkdir(parents=True);protected.write_bytes(b'active Mali wrapper')
        self.hw={'model':'anbernic,rg353v','panel':'anbernic,rg353v-panel-v2','gpu':'mali_kbase','fixed_libraries':[{'path':'usr/lib/libEGL.so.1','sha256':hashlib.sha256(protected.read_bytes()).hexdigest()}]}
        (self.meta/'hardware/profile.json').write_text(json.dumps(self.hw))
        self.payload=self.root/'usr/lib/libunused.so.1.0';self.payload.write_bytes(b'unused graphics')
        self.link=self.root/'usr/lib/libunused.so.1';self.link.symlink_to('libunused.so.1.0')
        self.policy={'schema':1,'profile':'rg353v-lean-v1','remove':{
            'usr/lib/libunused.so.1.0':{'sha256':hashlib.sha256(self.payload.read_bytes()).hexdigest(),'bytes':len(self.payload.read_bytes()),'group':'inactive_graphics'},
            'usr/lib/libunused.so.1':{'link':'libunused.so.1.0','group':'inactive_graphics'}}}
        self.path=self.root.parent/'policy.json'

    def prune(self,guard=lambda root,excluded:None):
        self.path.write_text(json.dumps(self.policy));return m.prune(self.root,self.path,guard)

    def test_reviewed_plan_removes_links_without_following_them_and_is_repeatable(self):
        result=self.prune();self.assertEqual(result['removed_bytes'],len(b'unused graphics'))
        self.assertFalse(self.payload.exists());self.assertFalse(self.link.is_symlink())
        self.assertEqual((self.root/'usr/lib/libEGL.so.1').read_bytes(),b'active Mali wrapper')
        report=self.meta/'hardware/image-prune.json';original=report.read_bytes();self.prune();self.assertEqual(report.read_bytes(),original)

    def test_dependency_guard_runs_before_any_unlink(self):
        def fail(root,excluded):
            self.assertTrue(self.payload.exists());self.assertIn('usr/lib/libunused.so.1',excluded)
            raise ValueError('needed by retained client')
        with self.assertRaisesRegex(ValueError,'retained client'):self.prune(fail)
        self.assertTrue(self.payload.exists());self.assertTrue(self.link.is_symlink())

    def test_changed_payload_or_alias_rejected_before_deletion(self):
        self.payload.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed image payload'):self.prune()
        self.assertTrue(self.link.is_symlink())
        self.payload.write_bytes(b'unused graphics');self.link.unlink();self.link.symlink_to('/outside')
        with self.assertRaisesRegex(ValueError,'Changed image link'):self.prune()
        self.assertTrue(self.payload.exists())

    def test_active_graphics_user_data_and_licenses_are_protected(self):
        for name in ('usr/lib/libEGL.so.1','usr/lib/libgbm.so.1','storage/slotcontent/Config/slot.state','usr/share/licenses/vendor/LICENSE','etc/passwd','etc/profile.d/another-helper','../outside'):
            self.policy['remove'][name]={'sha256':'x','group':'inactive_graphics'}
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Protected/invalid'):self.prune()
            self.policy['remove'].pop(name)
            self.assertTrue(self.payload.exists())

    def test_only_exact_legacy_controller_profile_is_permitted_and_hash_guarded(self):
        name='etc/profile.d/100-gamecontroller-functions'
        p=self.root/name;p.parent.mkdir(parents=True);p.write_bytes(b'old ES helper')
        self.policy['remove'][name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'group':'legacy_xml_controller_stack'}
        p.write_bytes(b'changed helper')
        with self.assertRaisesRegex(ValueError,'changed image payload'):self.prune()
        self.assertTrue(self.payload.exists())
        p.write_bytes(b'old ES helper');self.prune();self.assertFalse(p.exists())

    def test_parent_symlink_and_changed_fixed_graphics_are_rejected(self):
        self.policy['remove']['usr/lib/nested/payload']={'sha256':'x','group':'inactive_graphics'}
        (self.root/'usr/lib/nested').symlink_to('/outside')
        with self.assertRaisesRegex(ValueError,'parent symlink'):self.prune()
        self.assertTrue(self.payload.exists())
        self.policy['remove'].pop('usr/lib/nested/payload')
        (self.root/'usr/lib/libEGL.so.1').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'fixed graphics'):self.prune()
        self.assertTrue(self.payload.exists())

    def test_baseline_and_development_retain_payloads(self):
        for change in ({'userspace_profile':'baseline'},{'build_profile':'development'}):
            (self.meta/'os-profile.json').write_text(json.dumps(dict(self.factory,**change)))
            self.assertEqual(self.prune()['removed'],[]);self.assertTrue(self.payload.exists())

    def test_wrong_hardware_rejected(self):
        self.hw['gpu']='panfrost';(self.meta/'hardware/profile.json').write_text(json.dumps(self.hw))
        with self.assertRaisesRegex(ValueError,'Unqualified'):self.prune()

    def test_elf_graph_counts_real_sonames_and_rejects_missing_dependency(self):
        p=self.root/'usr/bin/client';p.parent.mkdir(parents=True)
        p.write_bytes(b'\x7fELF\x02\x01'+bytes(10)+b'\x03\x00\xb7\x00')
        lib=self.root/'usr/lib/libreal.so';lib.write_bytes(p.read_bytes())
        def readelf(args,**kwargs):
            text=' (NEEDED) Shared library: [libreal.so.1]' if args[-1].endswith('/client') else ' (SONAME) Library soname: [libreal.so.1]'
            return SimpleNamespace(stdout=text)
        with patch.object(m.subprocess,'run',readelf):
            m.check_dependencies(self.root,set())
            with self.assertRaisesRegex(ValueError,'unresolved'):m.check_dependencies(self.root,{'usr/lib/libreal.so'})


if __name__=='__main__':unittest.main()
