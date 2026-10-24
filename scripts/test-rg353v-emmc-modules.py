#!/usr/bin/env python3
"""Modular internal installer: real disposable disks, recovery and retry checks."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
s=load('setup','ports/rg353v/image/slot-setup.py');f=s.clean
i=load('publisher','ports/rg353v/image/slot-module-install.py')
d=load('debug','ports/rg353v/image/slot-setup-debug.py')

@unittest.skipUnless(os.environ.get('SLOT_EMMC_MODULE_IMAGE') and os.environ.get('SLOT_CLEAN_TEST')=='1','requires privileged disposable Linux loop disks')
class InternalModules(unittest.TestCase):
    def test_internal_publication_recovery_and_unchanged_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source_file=root/'source.img';target_file=root/'internal.img'
            subprocess.run(['cp','--sparse=always',os.environ['SLOT_EMMC_MODULE_IMAGE'],str(source_file)],check=True)
            with source_file.open('r+b') as stream:stream.truncate(512*f.MIB)
            with target_file.open('xb') as stream:stream.truncate(31_268_536_320)
            with target_file.open('r+b') as stream:stream.seek(32768);stream.write(b'old internal loader')
            source=Path(f.run('losetup','--find','--show','--partscan',source_file))
            target=Path(f.run('losetup','--find','--show','--partscan',target_file))
            flash=root/'flash';flash.mkdir();boot=root/'inspect-boot';boot.mkdir();store=root/'inspect-state';store.mkdir()
            before_nodes=set(Path('/dev').glob(source.name+'p*'))|set(Path('/dev').glob(target.name+'p*'))
            try:
                for n,g in f.initial_geometry().items():f.card.kernel_partition(source,n,g)
                f.run('mount','-o','ro',str(source)+'p1',flash)
                plan=json.loads((flash/f.MARKER).read_text());self.assertFalse(plan.get('sd_test',False))
                original=f.inventory(flash);profile=d.load(flash/d.PROFILE)
                # Verify the source kit before starting the destructive target transaction.
                seed=root/'seed';seed.mkdir();f.run('mount','-o','ro',str(source)+'p2',seed)
                catalog=i.catalog(seed,plan);selected=sorted(m['id'] for m in catalog['modules']);seed_inventory=f.inventory(seed)
                f.run('umount',seed)
                selection={'catalog':plan['module_catalog_sha256'],'selected':selected,'options':{'wifi':True,'usb':True,'ssh':True}}
                expected=s.identity(target,True)
                with target.open('rb') as stream:stream.seek(32768);old_loader=stream.read(s.LOADER_BYTES)
                def call(stop=None,fail_publication=False,install=selection,consent=None,source_plan=None):
                    work=root/('work'+str(len(list(root.glob('work*')))));work.mkdir()
                    def finish(storage,boot,journal,state,seed):
                        i.finalize(storage,boot,journal,state,plan,selected,d,profile,selection['options'],None,seed=seed)
                        if fail_publication:raise RuntimeError('Interrupted after module publication')
                    return s.install_internal(source,target,flash,work,source_plan or plan,expected,consent or s.confirmation(expected),test=True,stop=stop,finalize=finish,installation=install)
                with self.assertRaisesRegex(ValueError,'confirmation'):call(consent='no')
                with self.assertRaisesRegex(ValueError,'SD-only'):call(source_plan=dict(plan,sd_test=True))
                with self.assertRaisesRegex(RuntimeError,'after internal format'):call(stop='formatted')
                with self.assertRaisesRegex(ValueError,'different media or firmware'):call(install=dict(selection,selected=[]))
                with self.assertRaisesRegex(RuntimeError,'after module publication'):call(fail_publication=True)
                with target.open('rb') as stream:stream.seek(32768);self.assertEqual(stream.read(s.LOADER_BYTES),old_loader)
                # A complete verified publication must be durable before loader replacement.
                with self.assertRaisesRegex(RuntimeError,'before bootloader'):call(stop='verified')
                f.run('mount',str(target)+'p1',boot)
                with (boot/'SYSTEM').open('r+b') as stream:
                    original_byte=stream.read(1);stream.seek(0);stream.write(bytes([original_byte[0]^1]))
                f.run('umount',boot)
                with self.assertRaisesRegex(ValueError,'verification failed'):call()
                with target.open('rb') as stream:stream.seek(32768);self.assertEqual(stream.read(s.LOADER_BYTES),old_loader)
                f.run('mount',str(target)+'p1',boot)
                with (boot/'SYSTEM').open('r+b') as stream:stream.write(original_byte)
                f.run('umount',boot)
                result=call();self.assertEqual(result['phase'],'complete')
                self.assertEqual(call()['phase'],'complete','Completed install remains idempotent')
                f.run('mount','-o','ro',str(target)+'p1',boot)
                self.assertFalse((boot/'post-flash.sh').exists());self.assertFalse((boot/'slot-sd-test-guard').exists())
                self.assertIn(result['plan']['boot_uuid'],(boot/'extlinux/extlinux.conf').read_text())
                for name in f.HOOKS:self.assertFalse((boot/name).exists(),name)
                f.run('umount',boot)
                f.run('mount','-o','ro',str(target)+'p2',store)
                receipt=json.loads((store/'.slot-module-install-complete.json').read_text())
                self.assertEqual(receipt['selected'],selected)
                self.assertEqual((store/'.config/slot/developer-mode').read_text(),'1\n')
                self.assertEqual((store/'.config/slot/developer-usb').read_text(),'1\n')
                self.assertTrue((store/'.ssh/authorized_keys').is_file())
                self.assertEqual(i.m.digest(store/'.cache/ssh/ssh_host_ed25519_key'),plan['private_host_sha256'])
                self.assertFalse((store/'.slot-modules').exists(),'No second installer kit on eMMC')
                f.run('umount',store)
                with target.open('rb') as stream:
                    stream.seek(32768);import hashlib
                    self.assertEqual(hashlib.sha256(stream.read(s.LOADER_BYTES)).hexdigest(),s.LOADER_SHA)
                f.check_inventory(flash,original)
                f.run('mount','-o','ro',str(source)+'p2',seed)
                # Only the named internal-install recovery journal may be added to source storage.
                after=f.inventory(seed)
                self.assertEqual({k:v for k,v in after.items() if not k.startswith(s.JOURNAL+'/')},seed_inventory)
                self.assertTrue((seed/s.JOURNAL/'internal-first16MiB.bin').is_file());f.run('umount',seed)
                for n,command in ((1,['fsck.vfat','-n']),(2,['e2fsck','-fn']),(3,['fsck.exfat','-n'])):
                    subprocess.run(command+[str(target)+'p'+str(n)],check=True,stdout=subprocess.DEVNULL)
                self.assertEqual({n:(p['start'],p['bytes']) for n,p in f.card.table(target)[1].items()},f.emmc.geometry(expected['bytes']))
            finally:
                for path in (boot,store,flash,root/'seed'):subprocess.run(['umount',str(path)],capture_output=True)
                for disk in (target,source):
                    f.run('losetup','-d',disk)
                    for node in Path('/dev').glob(disk.name+'p*'):
                        if node not in before_nodes:node.unlink(missing_ok=True)

if __name__=='__main__':unittest.main()
