#!/usr/bin/env python3
"""OS boot selection, trial recovery, and partition/content preservation tests."""
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('os_updater', str(ROOT / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-os-update'))
spec = importlib.util.spec_from_loader(loader.name, loader)
o = importlib.util.module_from_spec(spec)
loader.exec_module(o)
u = o.u
delta_spec=importlib.util.spec_from_file_location('os_delta_builder',ROOT/'scripts/package-rg353v-os-delta.py')
delta=importlib.util.module_from_spec(delta_spec);delta_spec.loader.exec_module(delta)
OLD = {'api': 1, 'kernel': '7.0.2', 'os_build': 'old'}
NEW = dict(OLD, os_build='new')
CONFIG = 'LABEL ROCKNIX\n  LINUX /KERNEL\n  FDTDIR /device_trees\n  APPEND boot=LABEL=ROCKNIX disk=LABEL=STORAGE quiet console=tty0\n'


def elf():
    b = bytearray(64)
    b[:6] = b'\x7fELF\x02\x01'
    b[18:20] = (183).to_bytes(2, 'little')
    return b


class OSUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.factory = self.root / 'factory'
        self.system = self.factory / 'usr/share/slot/System'
        self.system.mkdir(parents=True)
        for name in ('slot', *u.CORES):
            (self.system / name).write_bytes(elf())
        (self.system / 'launch_frontend.sh').write_text('#!/bin/sh\n')
        self.manager = u.Manager(self.root / 'manager', OLD)
        self.manager.adopt(self.system, 'baseline')
        self.flash = self.root / 'flash'
        (self.flash / 'extlinux').mkdir(parents=True)
        (self.flash / 'extlinux/extlinux.conf').write_text(CONFIG)
        self.content = self.root / 'content/save.srm'
        self.content.parent.mkdir()
        self.content.write_bytes(b'latest progress')
        self.layout = {'GPT': 'unchanged', 'content': 'uuid-original'}
        self.profile = {'schema': 1, 'device': 'rg353v', 'arch': 'aarch64'}
        (self.factory / 'usr/share/slot/os-profile.json').write_text(json.dumps(self.profile))
        self.meta = {'schema': 1, 'kind': 'os', 'id': 'trial',
                     'target': {'device': 'rg353v', 'arch': 'aarch64'},
                     'runtime': NEW, 'profile': self.profile, 'compat': u.contract(self.system)}
        self.os = o.OSManager(self.root / 'os', self.flash, self.manager.root,
                              self.factory, OLD, lambda _: self.factory, lambda: self.layout.copy())
        self.inspected = {k: self.meta[k] for k in ('runtime', 'profile', 'compat')}
        self.addCleanup(patch.stopall)
        patch.object(o, 'inspect_system', return_value=self.inspected).start()
        patch.object(u, 'ensure_stopped').start()
        patch.object(o.OSManager, 'boot_instance', return_value='boot-1').start()
        self.package = self.root / 'os.tar'
        self.bundle()

    def bundle(self, extra=None, payload=None):
        payload = payload or {'KERNEL': b'kernel', 'SYSTEM': b'squashfs', 'device_trees/rg353v.dtb': b'dtb'}
        self.meta['files'] = {n: {'size': len(b), 'sha256': o.hashlib.sha256(b).hexdigest()} for n, b in payload.items()}
        with tarfile.open(self.package, 'w') as archive:
            entries = {'manifest.json': json.dumps(self.meta).encode(), **{'payload/' + n: b for n, b in payload.items()}}
            if extra:
                entries.update(extra)
            for name, data in entries.items():
                t = tarfile.TarInfo(name)
                t.size = len(data)
                archive.addfile(t, io.BytesIO(data))

    def delta_bundle(self):
        old={'KERNEL':b'kernel','SYSTEM':b'old squashfs','device_trees/rg353v.dtb':b'dtb'}
        self.meta['runtime']=OLD
        self.bundle(payload=old)
        base=self.root/'base.tar.gz';self.package.rename(base)
        for name,data in old.items():
            path=self.flash/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.meta['runtime']=NEW;self.bundle()
        target=self.root/'target.tar.gz';self.package.rename(target)
        delta.package(base,target,self.package)

    def mutate_delta(self,edit):
        with tarfile.open(self.package) as archive:
            entries={m.name:archive.extractfile(m).read() for m in archive.getmembers()}
        meta=json.loads(entries['manifest.json']);edit(meta,entries)
        entries['manifest.json']=json.dumps(meta).encode()
        with tarfile.open(self.package,'w:gz') as archive:
            for name,data in entries.items():
                entry=tarfile.TarInfo(name);entry.size=len(data);archive.addfile(entry,io.BytesIO(data))

    def test_os_delta_reconstructs_exact_files_and_uses_existing_trial_rollback(self):
        self.delta_bundle();self.stage()
        self.assertEqual((self.flash/'slot-os/trial/SYSTEM').read_bytes(),b'squashfs')
        self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'old squashfs')
        self.boot();self.os.manager().confirm('os-trial');self.assertTrue(self.os.confirm())
        self.os.rollback()
        self.assertEqual(self.os.boot_config.read_text(),CONFIG)
        self.assertEqual(self.content.read_bytes(),b'latest progress')

    def test_os_delta_wrong_base_rejected_without_boot_pointer_change(self):
        self.delta_bundle();(self.flash/'SYSTEM').write_bytes(b'corrupt')
        with self.assertRaisesRegex(u.UpdateError,'base checksum'):self.stage()
        self.assertEqual(self.os.boot_config.read_text(),CONFIG)
        self.assertIsNone(self.os.active());self.assertIsNone(self.manager.state()['pending'])
        self.assertFalse(list(self.os.root.glob('.stage-*')))

    def test_os_delta_refuses_corruption_and_invalid_ranges(self):
        self.delta_bundle();original=self.package.read_bytes()
        edits=[lambda m,e:e.__setitem__('patch/SYSTEM',b'X'*len(e['patch/SYSTEM'])),
               lambda m,e:m['recipes'].__setitem__('KERNEL',[['copy',0,999999]]),
               lambda m,e:m['recipes'].__setitem__('SYSTEM',[['data',1,8]]),
               lambda m,e:m.__setitem__('base_runtime',NEW),
               lambda m,e:e.pop('patch/SYSTEM'),
               lambda m,e:m['recipes'].__setitem__('SYSTEM',[['shell',0,8]])]
        for edit in edits:
            self.package.write_bytes(original);self.mutate_delta(edit)
            with self.assertRaises(u.UpdateError):self.stage()
            self.assertEqual(self.os.boot_config.read_text(),CONFIG)
            self.assertIsNone(self.os.active())
            self.assertEqual((self.flash/'SYSTEM').read_bytes(),b'old squashfs')

    def test_delta_boot_source_cannot_follow_a_symlink_outside_flash(self):
        (self.flash/'SYSTEM').symlink_to(self.content)
        with self.assertRaisesRegex(u.UpdateError,'unavailable'):self.os.boot_file('SYSTEM')

    def test_delta_boot_root_cannot_follow_an_external_directory(self):
        (self.flash/'slot-os').mkdir()
        (self.flash/'slot-os/escape').symlink_to(self.content.parent,target_is_directory=True)
        self.os.boot_config.write_text(o.new_boot_config(CONFIG,'escape'))
        with self.assertRaisesRegex(u.UpdateError,'boot partition'):self.os.boot_file('SYSTEM')

    def stage(self):
        return self.os.prepare(self.package, u.sha(self.package))

    def boot(self):
        self.os.environment = NEW
        self.os.boot_id = lambda: 'trial'
        self.os.boot()

    def confirm_version(self, name):
        self.meta['id'] = name
        self.bundle()
        self.stage()
        self.os.environment = NEW
        self.os.boot_id = lambda: name
        self.os.boot()
        self.os.manager().confirm('os-' + name)
        self.assertTrue(self.os.confirm())

    def test_retention_rotates_two_confirmed_versions_and_one_trial(self):
        for name in ('KERNEL', 'SYSTEM'):
            (self.flash/name).write_bytes(b'original factory')
        self.confirm_version('first')
        self.confirm_version('second')
        self.assertEqual({p.name for p in (self.flash/'slot-os').iterdir()}, {'first', 'second'})
        self.assertFalse((self.flash/'SYSTEM').exists())
        self.assertFalse((self.flash/'KERNEL').exists())
        self.assertEqual({p.name for p in self.manager.revisions.iterdir()}, {'os-first', 'os-second'})
        self.meta['id'] = 'third'; self.bundle(); self.stage()
        result = self.os.prune()
        self.assertEqual(result['retained_os'], ['first', 'second', 'third'])
        self.os.boot_id = lambda: 'third'; self.os.boot()
        self.os.manager().confirm('os-third'); self.os.confirm()
        self.assertEqual({p.name for p in (self.flash/'slot-os').iterdir()}, {'second', 'third'})
        self.assertEqual({p.name for p in self.manager.revisions.iterdir()}, {'os-second', 'os-third'})
        self.assertEqual({p.name for p in (self.os.root/'transactions').iterdir()}, {'second', 'third'})
        snapshot = (self.flash/'slot-os/third/previous-extlinux.conf').read_text()
        self.assertEqual(o.boot_payload_refs(snapshot), ({'second'}, False))
        self.assertNotIn('/slot-os/first/', self.os.active()['old_config'])
        self.assertEqual(self.content.read_bytes(), b'latest progress')
        self.os.prune()  # Repeating cleanup keeps the same pair.

    def test_retention_preserves_latest_rollback_and_bounds_older_recovery(self):
        self.confirm_version('first'); self.confirm_version('second'); self.confirm_version('third')
        self.os.rollback()
        self.assertEqual(self.manager.state()['current'], 'os-second')
        self.assertIsNone(self.manager.state()['previous'])
        self.os.boot_id = lambda: 'second'; self.os.boot()
        with self.assertRaisesRegex(u.UpdateError, 'No older OS'):
            self.os.rollback()
        self.assertEqual(self.content.read_bytes(), b'latest progress')

    def test_factory_stays_until_the_next_os_is_confirmed(self):
        for name in ('KERNEL', 'SYSTEM'):
            (self.flash/name).write_bytes(b'original factory')
        self.confirm_version('first')
        self.meta['id'] = 'second'; self.bundle(); self.stage()
        result = self.os.prune()
        self.assertTrue(result['factory_retained'])
        self.assertEqual(result['retained_os'], ['first', 'second'])
        self.assertTrue((self.flash/'SYSTEM').is_file())

    def test_running_another_os_refuses_cleanup(self):
        self.confirm_version('first'); self.confirm_version('second')
        self.os.boot_id = lambda: 'first'
        with self.assertRaisesRegex(u.UpdateError, 'Boot the confirmed OS'):
            self.os.prune()
        self.assertTrue((self.flash/'slot-os/second/SYSTEM').is_file())

    def test_retention_refuses_changed_partition_identity(self):
        self.confirm_version('first'); self.confirm_version('second')
        self.layout['GPT'] = 'another disk'
        with self.assertRaisesRegex(u.UpdateError, 'Partition identity changed'):
            self.os.prune()
        self.assertTrue((self.flash/'slot-os/first/SYSTEM').is_file())

    def test_retention_keeps_prior_pair_when_trial_is_rejected(self):
        self.confirm_version('first'); self.confirm_version('second')
        self.meta['id'] = 'bad'; self.bundle(); self.stage()
        self.os.rollback()  # Still running second: bad never reached its first boot.
        self.os.prune()
        self.assertEqual({p.name for p in (self.flash/'slot-os').iterdir()}, {'first', 'second'})
        self.assertEqual(self.manager.state()['current'], 'os-second')
        self.assertEqual(self.manager.state()['previous'], 'os-first')

    def test_retention_dry_run_and_old_archives(self):
        self.confirm_version('first'); self.confirm_version('second')
        archive = self.root/'.cache/slot-boot-archive/old'
        archive.mkdir(parents=True); (archive/'SYSTEM').write_bytes(b'old OS')
        before = self.os.active()
        result = self.os.prune(check_only=True)
        self.assertIn(str(archive), result['would_remove'])
        self.assertTrue(archive.exists())
        self.assertEqual(self.os.active(), before)
        self.os.prune(); self.assertFalse(archive.exists())

    def test_retention_refuses_symlinks_before_any_deletion(self):
        self.confirm_version('first'); self.confirm_version('second')
        orphan = self.flash/'slot-os/obsolete'; orphan.mkdir(); (orphan/'SYSTEM').write_bytes(b'old')
        link = self.flash/'slot-os/escape'; link.symlink_to(self.content.parent, target_is_directory=True)
        with self.assertRaisesRegex(u.UpdateError, 'Unexpected updater entry'):
            self.os.prune()
        self.assertTrue(orphan.exists())
        self.assertEqual(self.content.read_bytes(), b'latest progress')

    def test_retention_requires_intact_current_and_previous_payloads(self):
        self.confirm_version('first'); self.confirm_version('second')
        orphan = self.flash/'slot-os/obsolete'; orphan.mkdir()
        (self.flash/'slot-os/first/SYSTEM').write_bytes(b'corrupted')
        with self.assertRaisesRegex(u.UpdateError, 'Retained OS is damaged'):
            self.os.prune()
        self.assertTrue(orphan.exists())

    def test_retention_interrupted_deletion_is_retryable(self):
        self.confirm_version('first'); self.confirm_version('second')
        orphan = self.flash/'slot-os/obsolete'; orphan.mkdir()
        with patch.object(o.shutil, 'rmtree', side_effect=OSError('interrupted cleanup')):
            with self.assertRaises(OSError):
                self.os.prune()
        self.assertTrue((self.flash/'slot-os/first/SYSTEM').is_file())
        self.assertTrue((self.flash/'slot-os/second/SYSTEM').is_file())
        self.os.prune(); self.assertFalse(orphan.exists())

    def test_retention_reads_all_menu_entries_and_rejects_unknown_paths(self):
        text = o.new_boot_config(o.new_boot_config(CONFIG, 'first'), 'second')
        self.assertEqual(o.boot_payload_refs(text), ({'first', 'second'}, False))
        with self.assertRaises(u.UpdateError):
            o.boot_payload_refs(CONFIG.replace('/KERNEL', '/elsewhere/KERNEL'))
        with self.assertRaises(u.UpdateError):
            o.boot_payload_refs(CONFIG.replace('/KERNEL', '/../KERNEL'))

    def test_stage_and_confirm(self):
        self.stage()
        self.assertEqual(self.os.active()['phase'], 'staged')
        self.assertEqual((self.flash / 'slot-os/trial/previous-extlinux.conf').read_text(), CONFIG)
        self.assertEqual(self.manager.state()['current'], 'baseline')
        self.boot()
        self.os.boot()  # Same boot is idempotent.
        self.os.manager().confirm('os-trial')
        self.assertTrue(self.os.confirm())
        self.assertEqual(self.os.active()['phase'], 'confirmed')
        self.assertEqual(self.content.read_bytes(), b'latest progress')

    def test_stage_matches_uuid_arguments_to_mounted_filesystems(self):
        self.layout.update({'/flash': {'UUID': 'ABCD-1234'}, '/storage': {'UUID': 'storage-id'}})
        config = CONFIG.replace('boot=LABEL=ROCKNIX disk=LABEL=STORAGE',
                                'boot=UUID=abcd-1234 disk=UUID=storage-id')
        self.os.boot_config.write_text(config)
        self.stage()
        self.assertEqual((self.flash/'slot-os/trial/previous-extlinux.conf').read_text(), config)
        self.assertIn('boot=UUID=abcd-1234 disk=UUID=storage-id', self.os.boot_config.read_text())

    def test_optional_cache_write_failure_does_not_reject_confirmed_os(self):
        self.stage()
        self.boot()
        self.os.manager().confirm('os-trial')
        with patch.object(self.os, 'write_confirmed_boot_cache', side_effect=OSError('full volume')):
            self.assertTrue(self.os.confirm())
            self.os.boot()
        self.assertEqual(self.os.active()['phase'], 'confirmed')

    def test_uuid_arguments_cannot_select_another_disk(self):
        self.layout.update({'/flash': {'UUID': 'ABCD-1234'}, '/storage': {'UUID': 'storage-id'}})
        config = CONFIG.replace('boot=LABEL=ROCKNIX disk=LABEL=STORAGE',
                                'boot=UUID=ffff-9999 disk=UUID=storage-id')
        self.os.boot_config.write_text(config)
        with self.assertRaisesRegex(u.UpdateError, 'Unsupported boot/storage'):
            self.stage()
        self.assertEqual(self.os.boot_config.read_text(), config)

    def test_os_rollback_restores_boot_and_manager_only(self):
        self.stage()
        self.boot()
        self.os.manager().confirm('os-trial')
        self.os.confirm()
        self.content.write_bytes(b'newest progress')
        self.os.rollback()
        self.assertEqual(self.os.boot_config.read_text(), CONFIG)
        self.assertEqual(self.manager.state()['current'], 'baseline')
        self.assertIsNone(self.os.active())
        self.assertEqual(self.content.read_bytes(), b'newest progress')

    def test_card_reader_boot_restore_requests_matching_frontend(self):
        self.stage()
        self.boot()
        self.os.manager().confirm('os-trial')
        self.os.confirm()
        self.os.boot_config.write_text(CONFIG)
        self.os.boot_id = lambda: None
        with self.assertRaisesRegex(u.UpdateError, 'Previous OS selected'):
            self.os.boot()
        self.os.rollback()
        self.assertEqual(self.manager.state()['current'], 'baseline')

    def test_unconfirmed_second_boot_fails(self):
        self.stage()
        self.boot()
        with patch.object(o.OSManager, 'boot_instance', return_value='boot-2'):
            with self.assertRaisesRegex(u.UpdateError, 'restarted'):
                self.os.boot()

    def test_failed_userspace_trial_rolls_back(self):
        self.stage()
        self.boot()
        with patch.object(o, 'HEALTH_TIMEOUT', 0), patch.object(o.subprocess, 'run') as run:
            self.os.monitor()
        run.assert_called_once_with(['systemctl', 'reboot'], check=True)
        self.assertEqual(self.os.boot_config.read_text(), CONFIG)

    def test_busy_frontend_confirmation_retries_without_rollback(self):
        self.stage(); self.boot()
        with patch.object(self.os, 'confirm', side_effect=[u.UpdateBusy('busy'), u.UpdateBusy('busy'), True]) as confirm, \
             patch.object(self.os, 'rollback') as rollback, patch.object(o.time, 'sleep'):
            self.os.monitor()
        self.assertEqual(confirm.call_count, 3)
        rollback.assert_not_called()

    def test_real_manager_lock_contention_is_classified_as_busy(self):
        self.stage(); self.boot()
        with self.manager.locked():
            with self.assertRaises(u.UpdateBusy):
                self.os.confirm()

    def test_stage_copy_interruption_keeps_old_boot(self):
        with patch.object(o.shutil, 'copy2', side_effect=OSError('interrupted')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.stage()
        self.assertEqual(self.os.boot_config.read_text(), CONFIG)
        self.assertEqual(self.manager.state()['current'], 'baseline')
        self.os.rollback()

    def test_interruption_after_boot_switch_is_recoverable(self):
        original = self.os.save
        def save(record):
            if record['phase'] == 'staged':
                raise OSError('interrupted after config')
            original(record)
        with patch.object(self.os, 'save', side_effect=save):
            with self.assertRaisesRegex(OSError, 'after config'):
                self.stage()
        self.boot()
        self.assertEqual(self.os.active()['phase'], 'booting')
        self.os.rollback()
        self.assertEqual(self.os.boot_config.read_text(), CONFIG)

    def test_changed_partition_refuses_install_and_rollback(self):
        self.stage()
        self.layout['GPT'] = 'changed'
        with self.assertRaisesRegex(u.UpdateError, 'identity changed'):
            self.os.rollback()

    def test_unknown_boot_changes_refuse_rollback(self):
        self.stage()
        self.os.boot_config.write_text('other manual configuration')
        with self.assertRaisesRegex(u.UpdateError, 'outside the updater'):
            self.os.rollback()

    def test_check_has_no_boot_or_manager_side_effects(self):
        before = self.manager.state()
        self.os.prepare(self.package, u.sha(self.package), check_only=True)
        self.assertEqual(before, self.manager.state())
        self.assertEqual(self.os.boot_config.read_text(), CONFIG)
        self.assertIsNone(self.os.active())

    def test_reject_wrong_target_and_hash(self):
        with self.assertRaisesRegex(u.UpdateError, 'SHA-256'):
            self.os.prepare(self.package, '0' * 64)
        self.meta['target']['device'] = 'x55'
        self.bundle()
        with self.assertRaisesRegex(u.UpdateError, 'target'):
            self.stage()

    def test_reject_undeclared_files_and_traversal(self):
        for name in ('payload/extra', '../escape'):
            self.bundle({name: b'bad'})
            with self.assertRaises(u.UpdateError):
                self.stage()

    def test_reject_changed_save_contract(self):
        self.meta['compat']['sram'] = 2
        self.bundle()
        with self.assertRaisesRegex(u.UpdateError, 'migration'):
            self.stage()

    def retained_core_contract(self):
        path=self.manager.revisions/'baseline/revision.json'
        meta=json.loads(path.read_text())
        meta['compat']['states']['mgba_libretro.so']='a'*64
        path.write_text(json.dumps(meta))
        return meta['compat']

    def module_system(self):
        (self.system/'gpsp_libretro.so').unlink()
        u.atomic_json(self.system/'update-contract.json',{'schema':1,'settings':1,'sram':1,'cores':['mgba_libretro.so']})
        self.module_policy={'schema':1,'kit':'fixture','known':['emulator-mgba','emulator-gpsp','ssh','wifi'],
                            'selected':['emulator-mgba'],'optional':{'mgba_libretro.so':['emulator-mgba'],'gpsp_libretro.so':['emulator-gpsp'],'slot-ssh-ui':['ssh']}}
        u.atomic_json(self.system/u.MODULE_POLICY,self.module_policy)
        self.manager=u.Manager(self.root/'mod-manager',OLD);self.manager.adopt(self.system,'baseline')
        self.os=o.OSManager(self.root/'mod-os',self.flash,self.manager.root,self.factory,OLD,lambda _:self.factory,lambda:self.layout.copy())
        self.meta['compat']=u.contract(self.system);self.inspected['compat']=self.meta['compat'];self.bundle()

    def test_module_os_update_confirmation_and_rollback_keep_selection_and_content(self):
        self.module_system();self.stage();self.boot();self.os.manager().confirm('os-trial');self.assertTrue(self.os.confirm());self.os.rollback()
        baseline=self.manager.revision('baseline')/'System';self.assertEqual(u.module_policy(baseline)['selected'],['emulator-mgba'])
        self.assertEqual(self.content.read_bytes(),b'latest progress')

    def test_module_os_update_rejects_full_unfiltered_factory_and_missing_policy(self):
        self.module_system();(self.system/'slot-ssh-ui').write_text('restored by full OS')
        with self.assertRaisesRegex(u.UpdateError,'omitted module'):self.stage()
        (self.system/'slot-ssh-ui').unlink();(self.system/u.MODULE_POLICY).unlink()
        with self.assertRaisesRegex(u.UpdateError,'module selection'):self.stage()
        self.assertEqual((self.flash/'extlinux/extlinux.conf').read_text(),CONFIG)
        self.assertFalse(self.os.pointer.exists())

    def test_os_module_policy_checks_features_files_and_frontend_projection(self):
        self.module_system();prefix='usr/share/slot/System/'
        policy=dict(self.module_policy,optional={prefix+n:owners for n,owners in self.module_policy['optional'].items()})
        policy['optional']['usr/sbin/sshd']=['ssh']
        u.atomic_json(self.factory/'usr/share/slot/modules-v1.json',policy)
        features=self.factory/'usr/share/slot/features-v1';features.write_text('slot-features-v1\nemulator-mgba\n')
        self.assertEqual(u.os_module_policy(self.factory)['selected'],['emulator-mgba'])
        features.write_text('slot-features-v1\nemulator-mgba\nssh\n')
        with self.assertRaisesRegex(u.UpdateError,'menu disagrees'):u.os_module_policy(self.factory)
        features.write_text('slot-features-v1\nemulator-mgba\n');(self.factory/'usr/sbin').mkdir(parents=True);(self.factory/'usr/sbin/sshd').write_text('unselected daemon')
        with self.assertRaisesRegex(u.UpdateError,'omitted module'):u.os_module_policy(self.factory)

    def test_single_core_os_contract_preserves_selection_and_state_abi(self):
        for core in sorted(u.CORES):
            current = self.manager.verify_revision('baseline')
            current['compat']['states'] = {core: 'a' * 64}
            declared = o.copy.deepcopy(current['compat'])
            declared['states'][core] = 'b' * 64
            self.assertEqual(o.preserved_contract(declared, current, u.files(self.system)), current['compat'])
            for changed in ({}, {name: 'a' * 64 for name in u.CORES}):
                declared['states'] = changed
                with self.assertRaisesRegex(u.UpdateError, 'migration'):
                    o.preserved_contract(declared, current, u.files(self.system))

    def test_identical_cores_keep_component_state_contract_through_os_and_rollback(self):
        old=self.retained_core_contract()
        self.os.prepare(self.package,u.sha(self.package),check_only=True)
        self.stage()
        self.assertEqual(self.os.active()['compat'],old)
        self.boot();self.os.manager().confirm('os-trial');self.os.confirm()
        self.assertEqual(self.os.manager().verify_revision('os-trial')['compat'],old)
        self.os.rollback()
        self.assertEqual(self.manager.verify_revision('baseline')['compat'],old)
        self.assertEqual(self.content.read_bytes(),b'latest progress')

    def test_different_core_cannot_inherit_old_state_contract(self):
        self.retained_core_contract()
        (self.system/'mgba_libretro.so').write_bytes(elf()+b'changed core')
        self.meta['compat']=u.contract(self.system)
        self.inspected['compat']=self.meta['compat'];self.bundle()
        with self.assertRaisesRegex(u.UpdateError,'changed core'):
            self.stage()
        self.assertEqual(self.os.boot_config.read_text(),CONFIG)

    def test_identical_core_cannot_bypass_settings_or_sram_contract(self):
        old=self.retained_core_contract()
        current=self.manager.verify_revision('baseline');inventory=u.files(self.system)
        for key in ('config','sram'):
            declared=o.copy.deepcopy(old);declared[key]+=1
            with self.subTest(key=key),self.assertRaisesRegex(u.UpdateError,'migration'):
                o.preserved_contract(declared,current,inventory)

    def test_reject_mismatched_system_and_space(self):
        with patch.object(o, 'inspect_system', return_value={}):
            with self.assertRaisesRegex(u.UpdateError, 'do not match'):
                self.stage()
        with patch.object(o.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 1})()):
            with self.assertRaisesRegex(u.UpdateError, 'Insufficient'):
                self.stage()

    def test_boot_config_paths_and_arguments(self):
        new = o.new_boot_config(CONFIG, 'release-1')
        entry = o.boot_entries(new)
        self.assertEqual(entry['LINUX'], '/slot-os/release-1/KERNEL')
        self.assertEqual(o.arguments(entry)['SYSTEM_IMAGE'], '/slot-os/release-1/SYSTEM')
        self.assertIn('console=tty0', entry['APPEND'])
        self.assertIn('LABEL slot-previous', new)
        with self.assertRaisesRegex(u.UpdateError, 'Unsupported'):
            o.new_boot_config(CONFIG + '  INITRD /unknown\n', 'bad')


if __name__ == '__main__':
    unittest.main()
