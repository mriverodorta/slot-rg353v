#!/usr/bin/env python3
"""Real SD layout and interrupted module publication on a disposable loop disk."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    s=importlib.util.spec_from_file_location(name,ROOT/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('clean','ports/rg353v/image/slot-clean-firstboot.py')
i=load('install','ports/rg353v/image/slot-module-install.py')
d=load('debug','ports/rg353v/image/slot-setup-debug.py')

class Publication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=self.root/'storage';self.flash=self.root/'flash';self.journal=self.root/'journal'
        for p in (self.store,self.flash,self.journal):p.mkdir()
        self.plan={'disk_guid':'source-disk','module_catalog_sha256':'a'*64};self.state={}
        (self.flash/'SYSTEM').write_bytes(b'original')

    def publish(self,compose):
        with mock.patch.object(i,'catalog',return_value={}),mock.patch.object(i.m,'selection',return_value=['emulator-mgba']),mock.patch.object(i.m,'compose',side_effect=compose):
            i.finalize(self.store,self.flash,self.journal,self.state,self.plan,['emulator-mgba'],None,None,{},None)

    def compose(self,kit,chosen,work,output,progress):
        self.assertEqual(output,self.flash/'SYSTEM.modules-new')
        self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'original')
        self.assertEqual(json.loads((self.journal/'state.json').read_text())['module_staging'],i.staging_record(self.plan))
        output.write_bytes(b'verified system')
        return {'system_sha256':i.m.digest(output),'system_bytes':output.stat().st_size}

    def test_output_is_compressed_on_boot_then_published_without_ext4_copy(self):
        self.publish(self.compose)
        self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'verified system')
        self.assertFalse((self.store/'.slot-module-install/SYSTEM').exists())
        self.assertFalse((self.flash/'SYSTEM.modules-new').exists())

    def test_failed_compression_preserves_old_system_and_retry_removes_owned_partial(self):
        def interrupted(*args):
            args[3].write_bytes(b'partial compressed bytes')
            raise RuntimeError('power loss during compression')
        with self.assertRaisesRegex(RuntimeError,'power loss'):self.publish(interrupted)
        self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'original')
        self.assertTrue((self.flash/'SYSTEM.modules-new').exists())
        self.publish(self.compose)
        self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'verified system')

    def test_bad_verification_cannot_replace_original(self):
        def bad(*args):
            result=self.compose(*args);result['system_sha256']='0'*64;return result
        with self.assertRaisesRegex(ValueError,'verification failed'):self.publish(bad)
        self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'original')

    def test_unowned_or_mismatched_pending_is_preserved(self):
        pending=self.flash/'SYSTEM.modules-new';pending.write_bytes(b'unknown')
        for state in ({},{'module_staging':dict(i.staging_record(self.plan),source='other-disk')}):
            with self.assertRaisesRegex(ValueError,'Unknown boot'):i.discard_pending(self.flash,state,self.plan)
            self.assertEqual(pending.read_bytes(),b'unknown')

    def test_symlink_or_directory_stops_cleanup_before_any_deletion(self):
        state={'module_staging':i.staging_record(self.plan)}
        regular=self.flash/i.PENDING[0];regular.write_bytes(b'partial')
        other=self.flash/i.PENDING[1]
        for symlink in (True,False):
            if symlink:other.symlink_to(self.flash/'SYSTEM')
            else:other.mkdir()
            with self.assertRaisesRegex(ValueError,'Unsupported'):i.discard_pending(self.flash,state,self.plan)
            self.assertEqual(regular.read_bytes(),b'partial')
            other.unlink() if symlink else other.rmdir()
        self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'original')

@unittest.skipUnless(os.environ.get('SLOT_MODULE_IMAGE') and os.environ.get('SLOT_CLEAN_TEST')=='1','requires a privileged disposable Linux loop test')
class Install(unittest.TestCase):
    def test_sd_publication_can_resume_after_all_durable_phases(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'card.img'
            subprocess.run(['cp','--sparse=always',os.environ['SLOT_MODULE_IMAGE'],str(image)],check=True)
            with image.open('r+b') as out:out.truncate(8*1024**3)
            disk=Path(f.run('losetup','--find','--show','--partscan',image))
            flash=root/'flash';flash.mkdir();storage=root/'storage';storage.mkdir()
            before_nodes=set(Path('/dev').glob(disk.name+'p*'))
            try:
                for n,g in f.initial_geometry().items():f.card.kernel_partition(disk,n,g)
                f.run('mount',str(disk)+'p1',flash)
                plan=json.loads((flash/f.MARKER).read_text())
                original=f.inventory(flash)
                with disk.open('rb') as raw:raw.seek(32768);loader=raw.read(16*f.MIB-32768)
                profile=d.load(flash/'slot-setup-debug.json');f.run('umount',flash)
                for step,stop in enumerate(('relocated','formatted','compressed','published',None)):
                    f.run('mount',str(disk)+'p1',flash)
                    work=root/('work'+str(step));work.mkdir()
                    def finish(store,boot,journal,state):
                        catalog=i.catalog(store,plan)
                        selected=[m['id'] for m in catalog['modules'] if m['id'] not in ('sharing','network-time')]
                        if stop=='compressed':
                            original_compose=i.m.compose
                            def interrupted(*args):
                                original_compose(*args)
                                self.assertTrue((boot/'SYSTEM.modules-new').is_file())
                                self.assertFalse((store/'.slot-module-install/SYSTEM').exists())
                                raise RuntimeError('Intentional test interruption after boot compression')
                            with mock.patch.object(i.m,'compose',side_effect=interrupted):
                                i.finalize(store,boot,journal,state,plan,selected,d,profile,{'wifi':True,'usb':True,'ssh':True},None)
                        else:i.finalize(store,boot,journal,state,plan,selected,d,profile,{'wifi':True,'usb':True,'ssh':True},None)
                        if stop=='published':raise RuntimeError('Intentional test interruption after publication')
                    if stop:
                        with self.assertRaisesRegex(RuntimeError,'Intentional test interruption'):
                            f.setup(disk,flash,work,plan,test=True,stop=stop if stop in ('relocated','formatted') else None,finalize=finish)
                    else:f.setup(disk,flash,work,plan,test=True,finalize=finish)
                f.run('mount',str(disk)+'p1',flash)
                self.assertFalse((flash/f.MARKER).exists())
                if plan.get('sd_test'):
                    self.assertEqual(i.m.digest(flash/'slot-sd-test-guard'),plan['sd_guard_sha256'])
                    self.assertEqual((flash/'post-flash.sh').read_text(),i.GUARD)
                else:self.assertFalse((flash/'post-flash.sh').exists())
                self.assertNotEqual(i.m.digest(flash/'SYSTEM'),original['SYSTEM']['sha256'])
                for hook in f.HOOKS:
                    if hook!='post-flash.sh' or not plan.get('sd_test'):self.assertFalse((flash/hook).exists(),hook)
                f.run('umount',flash)
                f.run('mount',str(disk)+'p2',storage)
                result=json.loads((storage/'.slot-module-install-complete.json').read_text())
                self.assertNotIn('sharing',result['selected']);self.assertNotIn('network-time',result['selected'])
                self.assertTrue((storage/'.slot-modules').is_dir(),'kit survives until first healthy shelf')
                self.assertFalse((storage/f.INSTALL).exists())
                if profile:
                    self.assertEqual((storage/'.ssh/authorized_keys').stat().st_mode&0o777,0o600)
                    self.assertEqual((storage/'.cache/ssh/ssh_host_ed25519_key').stat().st_mode&0o777,0o600)
                else:
                    self.assertFalse((storage/'.ssh/authorized_keys').exists())
                    self.assertFalse((storage/'.cache/ssh/ssh_host_ed25519_key').exists())
                f.run('umount',storage)
                with disk.open('rb') as raw:raw.seek(32768);self.assertEqual(raw.read(len(loader)),loader)
                desired=f.emmc.geometry(8*1024**3)
                self.assertEqual({n:(p['start'],p['bytes']) for n,p in f.card.table(disk)[1].items()},desired)
                for cmd in (['e2fsck','-fn',str(disk)+'p2'],['fsck.vfat','-n',str(disk)+'p1'],['fsck.exfat','-n',str(disk)+'p3']):
                    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
            finally:
                subprocess.run(['umount',str(flash)],capture_output=True)
                subprocess.run(['umount',str(storage)],capture_output=True)
                f.run('losetup','-d',disk)
                for node in Path('/dev').glob(disk.name+'p*'):
                    if node not in before_nodes:node.unlink(missing_ok=True)

if __name__=='__main__':unittest.main()
