#!/usr/bin/env python3
"""Clean image guards and optional real first-boot loop/chroot qualification."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('clean', ROOT/'ports/rg353v/image/slot-clean-firstboot.py')
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)


def plan():
    return {'schema': f.PLAN_SCHEMA, 'kind': 'slot-clean-firstboot',
            'initial': dict(f.INITIAL),
            'final': dict(f.FINAL),
            'disk_guid': str(uuid.uuid4()), 'boot_uuid': '1234-ABCD',
            'storage_uuid': str(uuid.uuid4()),
            'partition_guids': {str(n): str(uuid.uuid4()) for n in (1,2,3)}}


class Guards(unittest.TestCase):
    def test_factory_boot_does_not_publish_extra_files_or_backups(self):
        spec = importlib.util.spec_from_file_location('composer',ROOT/'scripts/compose-rg353v-clean.py')
        composer = importlib.util.module_from_spec(spec); spec.loader.exec_module(composer)
        with tempfile.TemporaryDirectory() as folder:
            tree = Path(folder)
            for name in ('KERNEL','SYSTEM','KERNEL.md5','SYSTEM.md5'): (tree/name).touch()
            for name in ('device_trees','overlays','extlinux'): (tree/name).mkdir()
            (tree/'extlinux/extlinux.conf').touch()
            composer.validate_factory_boot(tree)
            private = tree/'authorized_keys'; private.write_text('private key installation')
            with self.assertRaises(ValueError): composer.validate_factory_boot(tree)
            private.unlink(); (tree/'extlinux/old-config.conf').touch()
            with self.assertRaises(ValueError): composer.validate_factory_boot(tree)

    def test_layout_and_schema_must_be_explicit(self):
        good = plan(); f.check_plan(good)
        for field, value in [('schema', 1), ('kind', 'existing-emmc'),
                             ('initial', {'boot_mib': 1024, 'storage_mib': 5120}),
                             ('final', {'boot_mib': 2048, 'storage_mib': 5120}),
                             ('boot_uuid', 'not-an-id'), ('storage_uuid', 'bad')]:
            with self.subTest(field=field):
                bad = dict(good); bad[field] = value
                with self.assertRaises((ValueError, KeyError)): f.check_plan(bad)
        bad = plan(); bad['partition_guids']['3'] = bad['partition_guids']['2']
        with self.assertRaises(ValueError): f.check_plan(bad)

    def test_starter_is_small_and_relocation_cannot_overlap_it(self):
        initial = f.initial_geometry(); final = f.emmc.geometry(31268536320)
        self.assertEqual(initial[1][1],224*f.MIB)
        self.assertEqual(f.STARTER_MIB,465)
        self.assertLess(sum(initial[2]), 512*f.MIB)
        self.assertLess(sum(initial[2]), final[2][0])
        self.assertEqual(final[1][1], 512*f.MIB)
        self.assertEqual(final[2][1], 512*f.MIB)
        self.assertEqual(final[3][1], 28779*f.MIB)
        with self.assertRaises(ValueError): f.emmc.geometry(7*1024**3)
        with self.assertRaises(ValueError): f.copy_region(Path('/never-open-this'), 1024, 2048, 4096)

    def test_legacy_receipt_stays_at_its_exact_layout_and_schema(self):
        legacy=plan();legacy.update(schema=1,final={'boot_mib':1024,'storage_mib':5120})
        old=f.final_geometry(legacy,31268536320);new=f.final_geometry(plan(),31268536320)
        self.assertEqual(old[1][1],1024*f.MIB);self.assertEqual(old[2][1],5120*f.MIB)
        self.assertEqual(new[3][1]-old[3][1],5120*f.MIB)
        legacy['schema']=f.PLAN_SCHEMA
        with self.assertRaises(ValueError):f.check_plan(legacy)

    def test_boot_backup_detects_changes_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); (root/'KERNEL').write_bytes(b'kernel')
            before = f.inventory(root); f.check_inventory(root, before)
            (root/'KERNEL').write_bytes(b'broken')
            with self.assertRaises(ValueError): f.check_inventory(root, before)
            (root/'link').symlink_to('KERNEL')
            with self.assertRaises(ValueError): f.inventory(root)

    def test_final_hook_order_allows_normal_boot_if_cleanup_is_interrupted(self):
        self.assertLess(f.HOOKS.index('post-sysroot.sh'), f.HOOKS.index('post-flash.sh'))
        source = (ROOT/'scripts/compose-rg353v-clean.py').read_text()
        self.assertIn('SYSTEM_TORAM=yes', source)
        self.assertIn('quiet console=ttyS2,1500000', source)
        self.assertNotIn('console=tty0', source)
        self.assertNotIn('copy_provision(', source)


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0 and os.environ.get('SLOT_INITRAMFS_ROOT'),
                     'requires the actual built ARM64 initramfs toolset')
class InitHandoff(unittest.TestCase):
    def test_source_selection_with_minimal_busybox(self):
        spec = importlib.util.spec_from_file_location('handoff_composer', ROOT/'scripts/compose-rg353v-clean.py')
        composer = importlib.util.module_from_spec(spec); spec.loader.exec_module(composer)
        selection = composer.RAM_RUN.split('slot_clean_disk=', 1)[1].split('for slot_clean_mount', 1)[0]
        selection = 'slot_clean_disk=' + selection
        with tempfile.TemporaryDirectory() as name:
            stage = Path(name)
            shutil.copytree(Path(os.environ['SLOT_INITRAMFS_ROOT']), stage, symlinks=True, dirs_exist_ok=True)
            for link, target in (('lib','usr/lib'), ('bin','usr/bin'), ('sbin','usr/sbin')):
                if not (stage/link).exists(): (stage/link).symlink_to(target)
            (stage/'proc').mkdir(exist_ok=True)
            script = stage/'probe.sh'
            script.write_text('fail() { exit 97; }\n' + selection + '\nprintf "%s\\n" "$slot_clean_disk"\n')
            missing = subprocess.run(['chroot', str(stage), '/usr/bin/busybox', 'readlink', '-f', '/dev/mmcblk1p1'],
                                     capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('applet not found', missing.stderr)
            for source, expected in (('/dev/mmcblk0p1','/dev/mmcblk0'), ('/dev/mmcblk1p1','/dev/mmcblk1'),
                                     ('/dev/mmcblk12p1','/dev/mmcblk12'), ('/dev/sda1', None)):
                (stage/'proc/mounts').write_text(source + ' /flash vfat ro 0 0\n')
                result = subprocess.run(['chroot', str(stage), '/usr/bin/busybox', 'sh', '/probe.sh'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if expected else 97, result.stderr)
                if expected: self.assertEqual(result.stdout.strip(), expected)


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0
                     and os.environ.get('SLOT_CLEAN_INTEGRATION') == '1',
                     'requires privileged disposable-image Linux container')
class Integration(unittest.TestCase):
    def test_actual_clean_image_relocation_interruptions_and_chroot(self):
        candidate = Path(os.environ['SLOT_CLEAN_IMAGE'])
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); image = root/'test.img'
            subprocess.run(['cp', '--sparse=always', str(candidate), str(image)], check=True)
            with image.open('r+b') as stream: stream.truncate(8*1024**3)
            disk = Path(f.run('losetup', '--find', '--show', '--partscan', image))
            old_nodes = {Path(str(disk)+'p'+str(n)) for n in (1,2,3) if Path(str(disk)+'p'+str(n)).exists()}
            sysroot = root/'sysroot'; sysroot.mkdir()
            ram = root/'ram'; ram.mkdir()
            flash = root/'flash'; flash.mkdir()
            store = root/'store'; store.mkdir()
            content = root/'content'; content.mkdir()
            ram_loop = None; binds = []
            run_prefix = Path('/run')/('slot-clean-test-'+uuid.uuid4().hex)
            run_prefix.mkdir()
            try:
                # Check the raw bootloader reserve, ignoring only bounded GPT/MBR bytes.
                with disk.open('rb') as stream:
                    stream.seek(32768); loader = stream.read(16*f.MIB-32768)
                for n,g in f.initial_geometry().items(): f.card.kernel_partition(disk,n,g)
                f.run('mount', str(disk)+'p1', flash)
                marker = json.loads((flash/f.MARKER).read_text())
                filesystem_uuid = marker['storage_uuid']
                original = f.inventory(flash)
                tools = run_prefix/'tools'; tools.mkdir()
                for filename in ('slot-clean-firstboot.py','slot-card-firstboot.py','slot-emmc-install.py'):
                    shutil.copyfile(flash/filename,tools/filename)
                # Execute the shipped Python and filesystem tools from the real
                # aarch64 SYSTEM, copied to tmpfs as on the first hardware boot.
                f.run('mount','-t','tmpfs','-o','size=512m','tmpfs',ram)
                shutil.copyfile(flash/'SYSTEM',ram/'SYSTEM')
                f.run('umount', flash)
                ram_loop = f.run('losetup','--find','--show','--read-only',ram/'SYSTEM')
                f.run('mount','-t','squashfs','-o','ro',ram_loop,sysroot)
                for name in ('dev','proc','sys','run'):
                    target = sysroot/name
                    f.run('mount','--bind','/'+name,target); binds.append(target)
                flash = sysroot/'flash'
                # Source the actual shipped FAT hook, as initramfs does. Its RAM
                # exec must release the script fd so FAT can be unmounted. The
                # production MMC guard deliberately refuses this loop device.
                f.run('mount',str(disk)+'p1',flash)
                handoff = subprocess.Popen(['chroot',str(sysroot),'/usr/bin/busybox','sh','-c',
                                           '. /flash/post-sysroot.sh'],
                                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                          text=True,start_new_session=True)
                try:
                    deadline = time.monotonic()+5
                    while time.monotonic()<deadline:
                        cmdline = Path('/proc')/str(handoff.pid)/'cmdline'
                        if cmdline.exists() and b'/run/slot-clean-tools/slot-clean-run.sh' in cmdline.read_bytes():
                            break
                        time.sleep(.02)
                    else:
                        self.fail('The sourced FAT hook did not exec its RAM continuation')
                    f.run('umount',flash)
                finally:
                    os.killpg(handoff.pid,signal.SIGKILL)
                    output,_ = handoff.communicate(timeout=5)
                    print(output,flush=True)
                    shutil.rmtree('/run/slot-clean-tools',ignore_errors=True)
                for key in ('disk_guid','partition_guids'):
                    wrong = json.loads(json.dumps(marker))
                    if key == 'disk_guid': wrong[key] = str(uuid.uuid4())
                    else: wrong[key]['2'] = str(uuid.uuid4())
                    with self.assertRaises(ValueError): f.validate(disk,wrong,8*1024**3)
                # Run twice with durable interruptions; the third pass completes.
                for index, stop in enumerate(('relocated', 'formatted', None)):
                    f.run('mount', str(disk)+'p1', flash)
                    command = ['chroot',str(sysroot),'/usr/bin/env','PATH=/usr/sbin:/usr/bin:/sbin:/bin',
                               'LC_ALL=C','LANG=C','PYTHONDONTWRITEBYTECODE=1','SLOT_CLEAN_TEST=1','/usr/bin/python3',
                               str(tools/'slot-clean-firstboot.py'),'--test','--disk',str(disk),
                               '--work',str(run_prefix/('work'+str(index)))]
                    if index == 0:
                        refused = list(command)
                        refused.remove('SLOT_CLEAN_TEST=1')
                        refused[-1] = str(run_prefix/'refused')
                        refused_env = dict(os.environ)
                        refused_env.pop('SLOT_CLEAN_TEST', None)
                        result = subprocess.run(refused,env=refused_env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                        self.assertNotEqual(result.returncode,0)
                        self.assertIn('Tests require an explicitly selected loop device',result.stdout)
                        # Refusal has not altered the starter FAT or either GPT.
                        f.check_inventory(flash,original)
                        self.assertEqual(f.card.table(disk)[1][2]['start'],f.initial_geometry()[2][0])
                    if stop: command += ['--stop-after',stop]
                    result = subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    print(result.stdout,flush=True)
                    if stop:
                        self.assertNotEqual(result.returncode,0)
                        self.assertIn('Intentional test interruption',result.stdout)
                    else:
                        self.assertEqual(result.returncode,0,result.stdout)
                    # A power loss after relocation leaves a bootable original FAT,
                    # the same UUIDs, and a durable backup on relocated ext4.
                    if stop:
                        f.run('mount', str(disk)+'p1', flash)
                        f.check_inventory(flash, original)
                        f.run('umount', flash)
                    if stop == 'formatted':
                        f.run('mount', str(disk)+'p3', content)
                        (content/'keep.txt').write_text('do not reformat completed content')
                        f.run('umount', content)
                desired = f.emmc.geometry(8*1024**3)
                _, actual = f.card.table(disk)
                self.assertEqual({n:(v['start'],v['bytes']) for n,v in actual.items()},desired)
                with disk.open('rb') as stream:
                    stream.seek(32768); self.assertEqual(stream.read(len(loader)), loader)
                f.run('mount', str(disk)+'p1', flash)
                remaining = f.inventory(flash)
                self.assertEqual(remaining, {k:v for k,v in original.items() if k not in f.HOOKS})
                self.assertGreater(os.statvfs(flash).f_blocks*os.statvfs(flash).f_frsize, 512*f.MIB-16*f.MIB)
                f.run('umount', flash)
                f.filesystem(str(disk)+'p2','ext4',filesystem_uuid)
                f.run('mount', str(disk)+'p2', store)
                self.assertEqual(json.loads((store/'.slot-clean-layout.json').read_text())['phase'],'complete')
                self.assertFalse((store/f.INSTALL).exists())
                self.assertFalse((store/'.please_resize_me').exists())
                fields = dict(line.split(':',1) for line in f.run('dumpe2fs','-h',str(disk)+'p2').splitlines() if ':' in line)
                self.assertEqual(int(fields['Block count'])*int(fields['Block size']),512*f.MIB)
                self.assertEqual(int(fields['Block size']),4096)
                # No settings or credentials imported by setup.
                self.assertFalse((store/'.ssh').exists()); self.assertFalse((store/'.cache').exists())
                f.run('umount', store)
                f.run('mount', str(disk)+'p3', content)
                self.assertEqual((content/'keep.txt').read_text(),'do not reformat completed content')
                for folder in f.CONTENT: self.assertTrue((content/folder).is_dir())
                f.run('umount', content)
                self.assertIn('No problems found', f.run('sgdisk','--verify',disk))
                subprocess.run(['e2fsck','-fn',str(disk)+'p2'],check=True)
                subprocess.run(['fsck.vfat','-n',str(disk)+'p1'],check=True)
                subprocess.run(['fsck.exfat','-n',str(disk)+'p3'],check=True)
            finally:
                for target in (content,store,flash):
                    subprocess.run(['umount',str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                for target in reversed(binds): f.run('umount',target)
                if ram_loop:
                    f.run('umount',sysroot); f.run('losetup','-d',ram_loop)
                subprocess.run(['umount',str(ram)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                shutil.rmtree(run_prefix)
                f.run('losetup','-d',disk)
                for n in (1,2,3):
                    node=Path(str(disk)+'p'+str(n))
                    if node not in old_nodes: node.unlink(missing_ok=True)


if __name__ == '__main__':
    import unittest.mock
    unittest.main()
