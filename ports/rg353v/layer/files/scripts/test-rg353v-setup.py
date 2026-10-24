#!/usr/bin/env python3
"""Destination/confirmation tests and real two-disk ARM64 installer qualification."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


setup=load('setup',ROOT/'ports/rg353v/image/slot-setup.py')
ui=load('ui',ROOT/'ports/rg353v/image/slot-setup-ui.py')
f=setup.clean


def info(total):return {'bytes':total,'content_bytes':f.emmc.geometry(total)[3][1]}


class Guards(unittest.TestCase):
    def test_remainder_for_different_real_media_capacities(self):
        for total in (8*1024**3,16_000_000_000,31_268_536_320,60_492_349_440,128_000_000_000,256_000_000_000):
            parts=f.emmc.geometry(total)
            self.assertEqual(parts[1],(16*f.MIB,512*f.MIB))
            self.assertEqual(parts[2],(528*f.MIB,512*f.MIB))
            self.assertEqual(sum(parts[3]),(total-33*512)//f.MIB*f.MIB)
            self.assertGreater(parts[3][1],0)
            self.assertLessEqual(sum(parts[3]),total-33*512)
        for total in (7*1024**3,31_268_536_321):
            with self.assertRaises(ValueError):f.emmc.geometry(total)

    def test_erase_requires_a_separate_positive_confirmation(self):
        m=ui.Model(info(64*1024**3),info(31_268_536_320))
        m.key('down');self.assertIsNone(m.key('a'));self.assertEqual(m.page,'confirm')
        self.assertEqual(m.selected,0);self.assertIsNone(m.key('a'));self.assertEqual(m.page,'choose')
        m.key('down');m.key('a');m.key('down')
        self.assertEqual(m.key('a'),'emmc');self.assertEqual(m.page,'progress')
        self.assertIsNone(m.key('a'));self.assertIsNone(m.key('b'))

    def test_sd_choice_cancel_and_internal_unavailable(self):
        m=ui.Model(info(64*1024**3),None)
        m.key('down');self.assertIsNone(m.key('a'));self.assertEqual(m.page,'choose')
        m.key('up');m.key('a');m.key('b');self.assertEqual(m.page,'choose')
        m.key('a');m.key('down');self.assertEqual(m.key('a'),'sd')
        m.page='done';self.assertEqual(m.key('a'),'reboot')
        m.page='choose';self.assertEqual(m.key('b'),'poweroff')

    def test_small_sd_can_be_an_internal_installer_without_sd_expansion(self):
        m=ui.Model({'bytes':512*1024**2,'content_bytes':None},info(31_268_536_320))
        self.assertIsNone(m.key('a'));self.assertEqual(m.page,'choose')
        m.key('down');m.key('a');self.assertEqual(m.page,'confirm')
        m.key('down');self.assertEqual(m.key('a'),'emmc')

    def test_native_input_codes_and_repeats(self):
        for kind,code,value,key in ((1,0x131,1,'a'),(1,0x130,1,'b'),(1,0x134,1,'y'),(1,0x220,1,'up'),
                                    (1,0x221,1,'down'),(3,0x11,-1,'up'),(3,0x11,1,'down')):
            self.assertEqual(ui.Input.decode(kind,code,value),key)
        for event in ((1,0x131,0),(1,0x131,2),(3,0x11,0),(1,116,1)):
            self.assertIsNone(ui.Input.decode(*event))

    def test_buttons_pressed_during_install_do_not_trigger_restart(self):
        reader,writer=os.pipe();os.set_blocking(reader,False)
        device=ui.Input.__new__(ui.Input);device.fds=[reader];device.hats={(reader,0x11):1}
        try:
            os.write(writer,ui.Input.EVENT.pack(0,0,1,0x131,1))
            device.drain()
            self.assertEqual(device.hats,{})
            with self.assertRaises(BlockingIOError):os.read(reader,ui.Input.EVENT.size)
        finally:os.close(reader);os.close(writer)

    def test_pad_hat_and_key_reports_do_not_move_selection_twice(self):
        device=ui.Input.__new__(ui.Input);device.hats={}
        self.assertEqual(device.feed(10,3,0x11,-1),'up')
        self.assertIsNone(device.feed(10,1,0x220,1))
        self.assertIsNone(device.feed(10,3,0x11,-1))
        self.assertIsNone(device.feed(10,3,0x11,0))
        self.assertIsNone(device.feed(10,1,0x220,0))
        self.assertEqual(device.feed(10,1,0x221,1),'down')
        self.assertIsNone(device.feed(10,3,0x11,1))

    def test_new_internal_ids_are_unique_from_the_source(self):
        a,b=setup.new_plan(),setup.new_plan();f.check_plan(a);f.check_plan(b)
        self.assertNotEqual(a['boot_uuid'],b['boot_uuid'])
        self.assertFalse(set(a['partition_guids'].values())&set(b['partition_guids'].values()))
        self.assertNotEqual(a['storage_uuid'],b['storage_uuid'])

    def test_font_and_all_setup_views_render_without_runtime_dependencies(self):
        canvas=ui.Canvas(ROOT/'ports/rg353v/image/slot-setup-font.json.gz')
        m=ui.Model(info(60_492_349_440),info(31_268_536_320))
        for page in ('choose','confirm','progress','done','error'):
            for action in ('sd','emmc'):
                m.page=page;m.action=action;m.status='Checking the installation';m.percent=90;m.draw(canvas)
                self.assertEqual(len(canvas.pixels),640*480*4)
                self.assertNotEqual(canvas.pixels,bytearray(bytes((*ui.BG,255))*(640*480)))
        self.assertTrue(ui.size(31_268_536_320).endswith('GiB'))


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0 and os.environ.get('SLOT_SETUP_INTEGRATION')=='1',
                     'requires privileged disposable two-disk Linux container')
class Native(unittest.TestCase):
    def test_sd_to_emmc_full_install_resume_and_independent_sd_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source_image=root/'source.img';target_image=root/'internal.img'
            subprocess.run(['cp','--sparse=always',os.environ['SLOT_CLEAN_IMAGE'],str(source_image)],check=True)
            with source_image.open('r+b') as out:out.truncate(512*1024**2)
            with target_image.open('xb') as out:out.truncate(31_268_536_320)
            # Include existing partitions and a recognizable old loader. The
            # installer must replace all partitions and write its loader last.
            f.run('sgdisk','--clear','--new=1:32768:163839','--new=2:163840:196607',target_image)
            with target_image.open('r+b') as out:out.seek(32768);out.write(b'original internal loader')
            source=Path(f.run('losetup','--find','--show','--partscan',source_image))
            target=Path(f.run('losetup','--find','--show','--partscan',target_image))
            nodes={p for disk in (source,target) for p in Path('/dev').glob(disk.name+'p*')}
            sysroot=root/'sysroot';sysroot.mkdir();flash=root/'flash';flash.mkdir()
            ram=root/'ram';ram.mkdir();state_mount=root/'state';state_mount.mkdir()
            target_boot=root/'target-boot';target_boot.mkdir();content=root/'content';content.mkdir()
            run_root=Path('/run')/('slot-setup-test-'+uuid.uuid4().hex);run_root.mkdir()
            binds=[];system_loop=None
            try:
                for n,g in f.initial_geometry().items():f.card.kernel_partition(source,n,g)
                f.card.kernel_partition(target,1,(16*f.MIB,64*f.MIB))
                f.card.kernel_partition(target,2,(80*f.MIB,16*f.MIB))
                f.run('mkfs.ext4','-q','-F',str(target)+'p1')
                f.run('mount',str(source)+'p1',flash)
                plan=json.loads((flash/f.MARKER).read_text());source_before=f.inventory(flash)
                selected=None
                if plan.get('module_catalog_sha256'):
                    f.run('mount','-o','ro',str(source)+'p2',state_mount)
                    selected=[item['id'] for item in json.loads((state_mount/'.slot-modules/catalog.json').read_text())['modules']]
                    f.run('umount',state_mount)
                tools=run_root/'tools';tools.mkdir()
                for p in flash.glob('*.py'):shutil.copyfile(p,tools/p.name)
                f.run('mount','-t','tmpfs','-o','size=512m','tmpfs',ram)
                shutil.copyfile(flash/'SYSTEM',ram/'SYSTEM');f.run('umount',flash)
                system_loop=f.run('losetup','--find','--show','--read-only',ram/'SYSTEM')
                f.run('mount','-t','squashfs','-o','ro',system_loop,sysroot)
                for n in ('dev','proc','sys','run'):
                    f.run('mount','--bind','/'+n,sysroot/n);binds.append(sysroot/n)
                # Resolve the exact joypad from the shipped base overlay without
                # loading any module into the Docker VM kernel.
                result=subprocess.run(['chroot',str(sysroot),'/usr/sbin/modprobe','-n','-d',
                                       '/usr/lib/kernel-overlays/base','-S','7.0.2','rocknix_singleadc_joypad'],
                                      stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                self.assertEqual(result.returncode,0,result.stdout)
                flash=sysroot/'flash';f.run('mount','-o','ro',str(source)+'p1',flash)
                with source.open('rb') as stream:stream.seek(32768);source_loader=stream.read(16*f.MIB-32768)
                with target.open('rb') as stream:stream.seek(32768);old_loader=stream.read(setup.LOADER_BYTES)
                harness=run_root/'native.py'
                harness.write_text('''import importlib.util,json,sys,os
from pathlib import Path
s=importlib.util.spec_from_file_location('setup',Path(__file__).parent/'tools/slot-setup.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
j=json.loads(Path(sys.argv[1]).read_text());source=Path(j['source']);target=Path(j['target']);work=Path(j['work']);work.mkdir()
plan=json.loads(Path('/flash/slot-clean-firstboot.json').read_text())
finish=None;internal_finish=None;installation=None
if j.get('selected'):
 i=m.clean.module('module_install','slot-module-install.py');d=m.clean.module('debug','slot-setup-debug.py')
 def publish(storage,boot,journal,state,seed=None):
  if j.get('stop')=='compressed':
   original=i.m.compose
   def interrupted(*args):
    original(*args)
    assert (boot/'SYSTEM.modules-new').is_file()
    assert not (storage/'.slot-module-install/SYSTEM').exists()
    raise RuntimeError('Intentional test interruption after boot compression')
   i.m.compose=interrupted
  i.finalize(storage,boot,journal,state,plan,j['selected'],d,None,{},None,seed=seed)
 finish=publish;internal_finish=publish
 installation={'catalog':plan['module_catalog_sha256'],'selected':j['selected'],'options':{}}
if j.get('sd'):
 m.clean.setup(source,Path('/flash'),work,plan,test=True,finalize=finish)
else:
 info=m.identity(target,True)
 m.install_internal(source,target,Path('/flash'),work,plan,info,j.get('consent',m.confirmation(info)),test=True,stop=j.get('stop'),finalize=internal_finish,installation=installation)
''')
                def call(**options):
                    request={'source':str(source),'target':str(target),'work':str(run_root/uuid.uuid4().hex),'selected':selected,**options}
                    job=run_root/(uuid.uuid4().hex+'.json');job.write_text(json.dumps(request))
                    result=subprocess.run(['chroot',str(sysroot),'/usr/bin/env','PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                                           'LC_ALL=C','LANG=C','PYTHONDONTWRITEBYTECODE=1','SLOT_CLEAN_TEST=1',
                                           '/usr/bin/python3',str(harness),str(job)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    print(result.stdout,flush=True)
                    # Release only unmounted RAM work files between retries.
                    path=Path(request['work'])
                    mounts=[line.split(' - ')[0].split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()]
                    if not any(v.startswith(str(path)) for v in mounts):shutil.rmtree(path,ignore_errors=True)
                    return result
                result=call(consent='no');self.assertNotEqual(result.returncode,0)
                self.assertIn('confirmation is required',result.stdout)
                result=call(sd=True);self.assertNotEqual(result.returncode,0)
                self.assertIn('SD setup requires at least 8 GiB',result.stdout)
                f.run('mount',str(target)+'p1',state_mount)
                result=call();self.assertNotEqual(result.returncode,0);self.assertIn('storage is mounted',result.stdout)
                f.run('umount',state_mount)
                result=call(target=str(source));self.assertNotEqual(result.returncode,0)
                self.assertIn('boot source',result.stdout)
                # Neither format nor installation can begin through these refusals.
                with target.open('rb') as stream:stream.seek(32768);self.assertEqual(stream.read(setup.LOADER_BYTES),old_loader)
                for stop in (('formatted','compressed','verified') if selected else ('formatted','verified')):
                    result=call(stop=stop);self.assertNotEqual(result.returncode,0)
                    self.assertIn('Intentional test interruption',result.stdout)
                    with target.open('rb') as stream:stream.seek(32768);self.assertEqual(stream.read(setup.LOADER_BYTES),old_loader)
                # Corruption during a paused install must block the loader write.
                f.run('mount',str(target)+'p1',target_boot)
                with (target_boot/'KERNEL').open('r+b') as stream:
                    original=stream.read(1);stream.seek(0);stream.write(bytes([original[0]^1]))
                f.run('umount',target_boot)
                result=call();self.assertNotEqual(result.returncode,0);self.assertIn('verification failed',result.stdout)
                with target.open('rb') as stream:
                    stream.seek(32768);self.assertEqual(stream.read(setup.LOADER_BYTES),old_loader)
                f.run('mount',str(target)+'p1',target_boot)
                with (target_boot/'KERNEL').open('r+b') as stream:stream.write(original)
                f.run('umount',target_boot)
                result=call();self.assertEqual(result.returncode,0,result.stdout)
                # A completed transaction is checked again and does not reformat.
                result=call();self.assertEqual(result.returncode,0,result.stdout)
                with target.open('rb') as stream:
                    stream.seek(32768);import hashlib
                    self.assertEqual(hashlib.sha256(stream.read(setup.LOADER_BYTES)).hexdigest(),setup.LOADER_SHA)
                _,parts=f.card.table(target);desired=f.emmc.geometry(31_268_536_320)
                self.assertEqual({n:(p['start'],p['bytes']) for n,p in parts.items()},desired)
                f.run('mount',str(target)+'p2',state_mount)
                receipt=json.loads((state_mount/'.slot-clean-layout.json').read_text());f.run('umount',state_mount)
                internal_plan=receipt['plan'];self.assertNotEqual(plan['boot_uuid'],internal_plan['boot_uuid'])
                self.assertNotEqual(plan['storage_uuid'],internal_plan['storage_uuid'])
                f.run('mount',str(target)+'p1',target_boot)
                text=(target_boot/'extlinux/extlinux.conf').read_text()
                self.assertIn('boot=UUID='+internal_plan['boot_uuid'],text)
                self.assertIn('disk=UUID='+internal_plan['storage_uuid'],text)
                self.assertNotIn(plan['storage_uuid'],text)
                for name in f.HOOKS:self.assertFalse((target_boot/name).exists())
                f.run('umount',target_boot)
                f.run('mount',str(target)+'p3',content)
                for folder in f.CONTENT:self.assertTrue((content/folder).is_dir())
                self.assertEqual([p for p in content.rglob('*') if p.is_file()],[])
                f.run('umount',content)
                f.check_inventory(flash,source_before)
                f.run('mount',str(source)+'p2',state_mount)
                journal=state_mount/setup.JOURNAL
                self.assertEqual(journal.stat().st_mode&0o777,0o700)
                for p in journal.glob('*.bin'):self.assertEqual(p.stat().st_mode&0o777,0o600)
                f.run('umount',state_mount)
                with source.open('rb') as stream:stream.seek(32768);self.assertEqual(stream.read(len(source_loader)),source_loader)
                self.assertEqual(f.card.table(source)[1][2]['start'],f.initial_geometry()[2][0])
                # The same image can instead expand the actual 60.49 GB SD;
                # internal partitions/content must remain unchanged.
                internal_before=f.card.table(target)
                # Grow the disposable backing file to model the larger SD
                # capacity; no real device changes capacity during setup.
                with source_image.open('r+b') as out:out.truncate(60_492_349_440)
                f.run('losetup','--set-capacity',source)
                result=call(sd=True);self.assertEqual(result.returncode,0,result.stdout)
                self.assertEqual(f.card.table(target),internal_before)
                sd_parts=f.card.table(source)[1];sd_desired=f.emmc.geometry(60_492_349_440)
                self.assertEqual({n:(p['start'],p['bytes']) for n,p in sd_parts.items()},sd_desired)
                self.assertGreater(sd_parts[3]['bytes'],parts[3]['bytes'])
                for disk in (source,target):
                    self.assertIn('No problems found',f.run('sgdisk','--verify',disk))
                    for n,command in ((1,['fsck.vfat','-n']),(2,['e2fsck','-fn']),(3,['fsck.exfat','-n'])):
                        subprocess.run(command+[str(disk)+'p'+str(n)],check=True)
            finally:
                for p in (content,state_mount,target_boot,flash):
                    subprocess.run(['umount',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                for p in reversed(binds):f.run('umount',p)
                if system_loop:f.run('umount',sysroot);f.run('losetup','-d',system_loop)
                subprocess.run(['umount',str(ram)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                shutil.rmtree(run_root,ignore_errors=True)
                for disk in (target,source):
                    f.run('losetup','-d',disk)
                    for p in Path('/dev').glob(disk.name+'p*'):
                        if p not in nodes:p.unlink(missing_ok=True)


if __name__=='__main__':unittest.main()
