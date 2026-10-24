#!/usr/bin/env python3
"""Exercise conversion closure and duplicate-library guards without hardware."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'ports/rg353v/rocknix/slot-startup-profile/tools/configure-appliance.py'
spec=importlib.util.spec_from_file_location('appliance',PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Appliance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_identical_sdl_is_replaced_by_relative_alias_and_repeat_is_safe(self):
        main=self.root/'usr/lib/libSDL2-2.0.so.0.3200.10';main.parent.mkdir(parents=True);main.write_bytes(b'qualified SDL')
        other=main.parent/'glesonly'/main.name;other.parent.mkdir();other.write_bytes(main.read_bytes())
        self.assertEqual(m.deduplicate_sdl(self.root),13)
        self.assertEqual(other.readlink(),Path('../'+main.name));self.assertEqual(other.read_bytes(),main.read_bytes())
        self.assertEqual(m.deduplicate_sdl(self.root),0)
    def test_different_sdl_variants_are_never_silently_replaced(self):
        main=self.root/'usr/lib/libSDL2-2.0.so.0.3200.10';main.parent.mkdir(parents=True);main.write_bytes(b'one')
        other=main.parent/'glesonly'/main.name;other.parent.mkdir();other.write_bytes(b'two')
        with self.assertRaisesRegex(ValueError,'variants differ'):m.deduplicate_sdl(self.root)
        self.assertEqual(other.read_bytes(),b'two')
    def test_conversion_alias_closure_excludes_removed_modules_and_is_repeatable(self):
        g=self.root/'usr/lib/gconv';(g/'gconv-modules.d').mkdir(parents=True)
        (g/'UTF-16.so').write_bytes(b'module');(g/'IBM850.so').write_bytes(b'module')
        (g/'gconv-modules').write_text('alias CP850// IBM850//\nalias DOS// CP850//\nalias NOTHERE// REMOVED//\nmodule IBM850// INTERNAL IBM850 1\nmodule REMOVED// INTERNAL REMOVED 1\n')
        (g/'gconv-modules.d/extra.conf').write_text('module UTF-16LE// INTERNAL UTF-16 1\n')
        (g/'gconv-modules.cache').write_bytes(b'stale cache')
        m.compact_gconv(self.root);text=(g/'gconv-modules').read_text()
        self.assertIn('DOS// CP850//',text);self.assertIn('UTF-16LE//',text);self.assertNotIn('REMOVED',text)
        self.assertFalse((g/'gconv-modules.cache').exists());m.compact_gconv(self.root)
        self.assertEqual((g/'gconv-modules').read_text(),text)
    def test_new_policy_preserves_core_drivers_source_notices_and_unicode(self):
        import json
        p=json.loads((PATH.parents[1]/'config/appliance-prune.json').read_text())['remove']
        for n in p:
            self.assertNotIn('/licenses/',n);self.assertNotIn('libmali.so',n)
            self.assertFalse(n.startswith('usr/share/slot/System/'))
        for n in ('UTF-16','UTF-32','UNICODE','IBM850','CP1252'):
            self.assertNotIn('usr/lib/gconv/'+n+'.so',p)
    def test_factory_image_inputs_survive_runtime_removal_in_build_cache(self):
        folder=self.root/'usr/share/bootloader';folder.mkdir(parents=True)
        (folder/'Generic_uboot.bin').write_bytes(b'factory raw-sector input')
        cache=self.root/'cache/bootloader';m.stage_boot_artifacts(self.root,cache)
        m.stage_boot_artifacts(self.root,cache)
        (folder/'Generic_uboot.bin').unlink()
        self.assertEqual((cache/'Generic_uboot.bin').read_bytes(),b'factory raw-sector input')
        (folder/'Generic_uboot.bin').write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError,'Changed cached'):m.stage_boot_artifacts(self.root,cache)

    def test_accessory_tools_do_not_remove_audio_or_python_archive_apis(self):
        import json
        policy=json.loads((PATH.parents[1]/'config/appliance-prune.json').read_text())['remove']
        for name in ('usr/bin/aconnect','usr/bin/alsaucm','usr/bin/speaker-test',
                     'usr/bin/jq','usr/bin/ziptool','usr/bin/zipcmp','usr/bin/zipmerge',
                     'usr/sbin/rpcbind','usr/bin/rpcinfo'):
            self.assertIn(name,policy)
            self.assertRegex(policy[name]['sha256'],r'^[0-9a-f]{64}$')
        for name in ('usr/bin/amixer','usr/sbin/alsactl','usr/bin/aplay',
                     'usr/bin/slot-audio-route','usr/bin/slot-speaker-start',
                     'usr/lib/libasound.so.2.0.0','usr/lib/python3.14/zipfile/__init__.pyc',
                     'usr/lib/python3.14/tarfile.pyc','usr/bin/userconfig-setup'):
            self.assertNotIn(name,policy)
        for name,target in {'libzip.so':'libzip.so.5','libzip.so.5':'libzip.so.5.5',
                            'libonig.so':'libonig.so.5','libonig.so.5':'libonig.so.5.5.0'}.items():
            self.assertEqual(policy['usr/lib/'+name]['link'],target)

    def test_samba_is_pruned_before_its_gnutls_dependency_family(self):
        import json
        meta=self.root/'usr/share/slot';meta.mkdir(parents=True)
        (meta/'os-profile.json').write_text(json.dumps({'userspace_profile':'rg353v-lean-v1','build_profile':'normal'}))
        marker=self.root/'usr/sbin/ksmbd.mountd';marker.parent.mkdir(parents=True);marker.touch()
        calls=[]
        def backend(root):calls.append('samba');return {'backend':'ksmbd'}
        def trim(*args,**kwargs):
            calls.append('dependencies')
            self.assertEqual(calls,['samba','dependencies'])
            raise RuntimeError('stop before hardware setup')
        def load(name,filename):
            return SimpleNamespace(prune=backend if filename=='configure-ksmbd.py' else trim)
        with patch.object(m,'load',load),self.assertRaisesRegex(RuntimeError,'hardware setup'):
            m.configure(self.root)
        self.assertEqual(calls,['samba','dependencies'])

if __name__=='__main__':unittest.main()
