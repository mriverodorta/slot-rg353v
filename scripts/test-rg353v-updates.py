#!/usr/bin/env python3
"""Updater transaction, corruption and startup recovery regressions (no device)."""
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-update'
loader = importlib.machinery.SourceFileLoader('updater', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
u = importlib.util.module_from_spec(spec)
loader.exec_module(u)
ENV = {'api': 1, 'os_build': 'fixture-rocknix', 'kernel': 'fixture-kernel'}


def binary(label):
    header = bytearray(64)
    header[:6] = b'\x7fELF\x02\x01'
    header[18:20] = (183).to_bytes(2, 'little')
    return bytes(header) + label.encode()


class Updates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.system = self.root / 'System'
        self.system.mkdir()
        for name in ('slot', *u.CORES):
            p = self.system / name
            p.write_bytes(binary(name))
            p.chmod(0o755)
        (self.system / 'launch_frontend.sh').write_text('#!/bin/sh\nexit 0\n')
        (self.system / 'update-contract.json').write_text('{"schema":1,"settings":1,"sram":1}')
        (self.system / 'licenses').mkdir()
        (self.system / 'licenses/core-sources').mkdir()
        (self.system / 'licenses/core-sources/test.meta').write_text('source evidence\n')
        self.manager = u.Manager(self.root / 'managed', ENV)
        self.manager.adopt(self.system, 'known-good')
        self.base = self.manager.revision('known-good') / 'revision.json'
        self.content = self.root / 'content'
        for name in ('Games/g.gba', 'Saves/g.sav', 'States/resume.state', 'Config/slot.state', 'Wallpapers/bg.png'):
            p = self.content / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('user content ' + name)
        self.before = u.files(self.content)

    def tearDown(self):
        self.assertEqual(u.files(self.content), self.before)
        self.tmp.cleanup()

    def make(self, name='candidate', kind='slot', states_compatible=False, delta=False):
        path = self.root / (name + '.tar.gz')
        u.package(self.system, self.base, kind, name, path, states_compatible, delta)
        return path

    def test_delta_only_carries_changed_files_and_hardlinks_retained_bytes(self):
        (self.system/'slot').write_bytes(binary('new frontend'))
        package=self.make(delta=True)
        with tarfile.open(package) as archive:
            self.assertEqual(set(archive.getnames()), {'manifest.json','payload/slot'})
            self.assertEqual(json.load(archive.extractfile('manifest.json'))['schema'],2)
        self.install(package)
        old=self.manager.revision('known-good')/'System'
        new=self.manager.revision('candidate')/'System'
        self.assertNotEqual((old/'slot').stat().st_ino,(new/'slot').stat().st_ino)
        self.assertEqual((old/'mgba_libretro.so').stat().st_ino,(new/'mgba_libretro.so').stat().st_ino)
        self.assertEqual((old/'slot').read_bytes(),binary('slot'))
        trial,_=self.manager.select();self.manager.confirm(trial);self.manager.rollback()
        self.assertEqual(self.manager.state()['current'],'known-good')
        self.manager.verify_revision('known-good')

    def test_wrong_declared_target_inventory_is_rejected_before_activation(self):
        (self.system/'slot').write_bytes(binary('new frontend'))
        package=self.meta(self.make(delta=True),lambda m:m.update(target_sha256='0'*64))
        with self.assertRaisesRegex(u.UpdateError,'Target inventory checksum'):
            self.install(package)
        self.assertIsNone(self.manager.state()['pending'])
        self.manager.verify_revision('known-good')

    def test_delta_deletion_only_and_mode_only_do_not_modify_rollback(self):
        (self.system/'licenses/core-sources/test.meta').unlink()
        package=self.make(kind='cores',delta=True)
        with tarfile.open(package) as archive:
            self.assertEqual(archive.getnames(),['manifest.json'])
        self.install(package)
        self.assertTrue((self.manager.revision('known-good')/'System/licenses/core-sources/test.meta').exists())
        self.assertFalse((self.manager.revision('candidate')/'System/licenses/core-sources/test.meta').exists())
        self.manager.rollback()
        (self.system/'launch_frontend.sh').chmod(0o755)
        self.install(self.make('mode-only',delta=True))
        self.assertEqual((self.manager.revision('known-good')/'System/launch_frontend.sh').stat().st_mode&0o777,0o644)
        self.assertEqual((self.manager.revision('mode-only')/'System/launch_frontend.sh').stat().st_mode&0o777,0o755)

    def test_delta_refuses_wrong_base_and_false_deletions_before_activation(self):
        (self.system/'slot').write_bytes(binary('new'))
        for number,change in enumerate([
                lambda m:m.update(base_sha256='0'*64),
                lambda m:m.update(removed=['launch_frontend.sh']),
                lambda m:m.update(changed={}),
                lambda m:m['changed'].update({'invented':{'size':0}})]):
            package=self.meta(self.make('bad-delta-'+str(number),delta=True),change)
            with self.assertRaises(u.UpdateError):self.install(package)
            self.assertIsNone(self.manager.state()['pending'])
            self.manager.verify_revision('known-good')
        self.assertFalse(list(self.manager.revisions.glob('.install-*')))

    def test_delta_selected_modules_stay_selected_and_trial_failure_rolls_back(self):
        self.select_modules(['diagnostics'])
        (self.system/'slot-diagnostics-ui').write_text('new helper')
        self.install(self.make(delta=True))
        trial,_=self.manager.select()
        self.assertEqual(trial,'candidate')
        selected,_=self.manager.select()
        self.assertEqual(selected,'known-good')
        self.assertEqual(u.module_policy(self.manager.revision(selected)/'System')['selected'],sorted(self.policy['selected']))
        self.assertFalse((self.manager.revision(trial)/'System/slot-ssh-ui').exists())

    def test_empty_delta_is_rejected(self):
        with self.assertRaisesRegex(u.UpdateError,'no changes'):self.make(delta=True)

    def install(self, package=None):
        package = package or self.make()
        self.manager.install(package, u.sha(package))

    def rewrite(self, package, change):
        with tarfile.open(package) as archive:
            rows = [(m, archive.extractfile(m).read()) for m in archive.getmembers()]
        changed = change(rows)
        with tarfile.open(package, 'w:gz') as archive:
            for member, data in changed:
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return package

    def meta(self, package, change):
        def apply(rows):
            result = []
            for member, data in rows:
                if member.name == 'manifest.json':
                    value = json.loads(data)
                    change(value)
                    data = json.dumps(value).encode()
                result.append((member, data))
            return result
        return self.rewrite(package, apply)

    def select_one(self, core):
        for name in u.CORES - {core}:
            (self.system / name).unlink()
        u.atomic_json(self.system / 'update-contract.json',
                      {'schema': 1, 'settings': 1, 'sram': 1, 'cores': [core]})
        self.manager = u.Manager(self.root / 'single-managed', ENV)
        self.manager.adopt(self.system, 'known-good')
        self.base = self.manager.revision('known-good') / 'revision.json'

    def select_modules(self, extra=()):
        self.select_one('mgba_libretro.so')
        known=['emulator-mgba','emulator-gpsp','ssh','sharing','diagnostics']
        optional={'mgba_libretro.so':['emulator-mgba'],'gpsp_libretro.so':['emulator-gpsp'],
                  'slot-ssh-ui':['ssh'],'slot-sharing-ui':['sharing'],'slot-diagnostics-ui':['diagnostics']}
        self.policy={'schema':1,'kit':'test-kit','known':known,'selected':['emulator-mgba',*extra],'optional':optional}
        for name,owners in optional.items():
            if set(owners)&set(self.policy['selected']) and not (self.system/name).exists(): (self.system/name).write_text('selected helper')
        u.atomic_json(self.system/u.MODULE_POLICY,self.policy)
        self.manager=u.Manager(self.root/'modules-managed',ENV)
        self.manager.adopt(self.system,'known-good')
        self.base=self.manager.revision('known-good')/'revision.json'

    def test_module_frontend_core_confirmation_and_rollback_preserve_data_and_optional_helpers(self):
        self.select_modules(['diagnostics'])
        (self.system/'slot').write_bytes(binary('updated frontend'))
        self.install(); name,_=self.manager.select();self.manager.confirm(name)
        self.base=self.manager.revision(name)/'revision.json'
        (self.system/'mgba_libretro.so').write_bytes(binary('updated core'))
        self.install(self.make('new-core','cores',True));name,_=self.manager.select();self.manager.confirm(name)
        for action in [self.manager.rollback,self.manager.rollback]:
            action();name,_=self.manager.select();system=self.manager.revision(name)/'System'
            self.assertEqual(u.module_policy(system)['selected'],sorted(self.policy['selected']))
            self.assertTrue((system/'slot-diagnostics-ui').exists());self.assertFalse((system/'slot-ssh-ui').exists())
            self.assertFalse((system/'slot-sharing-ui').exists());self.assertEqual(u.files(self.content),self.before)

    def test_module_builder_rejects_extra_helpers_and_missing_selected_payload(self):
        self.select_modules(['diagnostics'])
        (self.system/'slot-ssh-ui').write_text('accidental full build')
        with self.assertRaisesRegex(u.UpdateError,'omitted module'):self.make()
        (self.system/'slot-ssh-ui').unlink();(self.system/'slot-diagnostics-ui').unlink()
        with self.assertRaisesRegex(u.UpdateError,'selected module'):self.make()

    def test_module_package_consumer_rejects_tampered_policy_and_reintroduced_helper(self):
        self.select_modules(); good=self.make()
        bad=self.meta(good,lambda meta:meta.pop('modules'))
        with self.assertRaisesRegex(u.UpdateError,'module selection'):self.install(bad)
        good=self.make('good')
        data=b'excluded ssh helper'
        def inject(rows):
            result=[]
            for member,payload in rows:
                if member.name=='manifest.json':
                    meta=json.loads(payload);meta['files']['slot-ssh-ui']={'size':len(data),'sha256':u.hashlib.sha256(data).hexdigest(),'mode':0o755};payload=json.dumps(meta).encode()
                result.append((member,payload))
            entry=tarfile.TarInfo('payload/slot-ssh-ui');entry.mode=0o755;result.append((entry,data));return result
        self.rewrite(good,inject)
        with self.assertRaisesRegex(u.UpdateError,'omitted module'):self.install(good)
        self.assertIsNone(self.manager.state()['pending'])

    def test_modules_failed_trial_and_corrupt_current_return_to_same_selection(self):
        self.select_modules();self.install();trial,_=self.manager.select()
        selected,_=self.manager.select();self.assertEqual(selected,'known-good')
        # A fresh candidate confirms, then damaged current metadata must still recover.
        self.install(self.make('second'));trial,_=self.manager.select();self.manager.confirm(trial)
        (self.manager.revision(trial)/'revision.json').write_text('broken metadata')
        selected,_=self.manager.select();self.assertEqual(selected,'known-good')
        self.assertEqual(self.manager.state()['module_selection'],['emulator-mgba'])

    def test_production_verifier_refuses_missing_or_inconsistent_runtime_module_records(self):
        self.select_modules();record=self.root/'runtime-modules';features=self.root/'runtime-features'
        with patch.object(u,'MODULE_RECORD',record),patch.object(u,'MODULE_FEATURES',features),patch.object(self.manager,'env',return_value=ENV):
            self.manager.environment=None
            with self.assertRaisesRegex(u.UpdateError,'record is missing'):self.manager.verify_revision('known-good')
            u.atomic_json(record,self.policy);features.write_text('slot-features-v1\nemulator-mgba\n')
            self.manager.verify_revision('known-good')
            features.write_text('slot-features-v1\nemulator-mgba\nssh\n')
            with self.assertRaisesRegex(u.UpdateError,'feature menu'):self.manager.verify_revision('known-good')

    def test_runtime_cache_covers_module_and_feature_records_when_present(self):
        with patch.object(u,'RUNTIME_FILES',()), patch.object(u,'MODULE_RECORD',self.root/'modules.json'),patch.object(u,'MODULE_FEATURES',self.root/'features'):
            self.assertEqual(u.runtime_files(),())
            (self.root/'modules.json').write_text('{}');(self.root/'features').write_text('slot-features-v1')
            self.assertEqual(set(u.runtime_files()),{self.root/'modules.json',self.root/'features'})

    def test_single_emulator_frontend_core_update_and_rollback_preserve_selection(self):
        for core in sorted(u.CORES):
            with self.subTest(core=core):
                # Each subcase has its own isolated content and manager.
                other = Updates(); other.setUp()
                try:
                    other.select_one(core)
                    self.assertEqual(set(u.load(other.base)['compat']['states']), {core})
                    (other.system / 'slot').write_bytes(binary('single frontend'))
                    other.install(other.make())
                    name, _ = other.manager.select(); other.manager.confirm(name)
                    other.base = other.manager.revision(name) / 'revision.json'
                    (other.system / core).write_bytes(binary('single updated core'))
                    other.install(other.make(name='core-trial', kind='cores', states_compatible=True))
                    name, _ = other.manager.select(); other.manager.confirm(name)
                    installed = other.manager.revision(name) / 'System'
                    self.assertEqual(u.CORES & u.files(installed).keys(), {core})
                    self.assertEqual(u.installed_cores(installed), {core})
                    other.manager.rollback()
                    self.assertEqual(u.installed_cores(other.manager.revision('candidate') / 'System'), {core})
                finally: other.tearDown()

    def test_single_emulator_rejects_producer_and_consumer_reintroduction(self):
        self.select_one('mgba_libretro.so')
        good = self.make(kind='cores')
        # Add a valid ELF and its correct inventory hash to simulate a full-core publisher.
        payload = binary('extra emulator')
        def inject(rows):
            for member, data in rows:
                if member.name == 'manifest.json':
                    meta = json.loads(data)
                    meta['files']['gpsp_libretro.so'] = {'size': len(payload), 'mode': 0o755,
                                                       'sha256': u.hashlib.sha256(payload).hexdigest()}
                    data = json.dumps(meta).encode()
                yield member, data
            entry = tarfile.TarInfo('payload/gpsp_libretro.so')
            yield entry, payload
        self.rewrite(good, inject)
        with self.assertRaisesRegex(u.UpdateError, 'preserve the installed emulator'):
            self.install(good)
        (self.system / 'gpsp_libretro.so').write_bytes(payload)
        (self.system / 'gpsp_libretro.so').chmod(0o755)
        with self.assertRaisesRegex(u.UpdateError, 'unselected emulator'):
            self.make()
        u.atomic_json(self.system / 'update-contract.json',
                      {'schema': 1, 'settings': 1, 'sram': 1, 'cores': sorted(u.CORES)})
        with self.assertRaisesRegex(u.UpdateError, 'preserve installed emulators'):
            self.make()
        self.assertIsNone(self.manager.state()['pending'])

    def test_emulator_declarations_fail_closed_and_legacy_still_requires_both(self):
        for declaration in (None, [], {'cores': []}, {'cores': 'mgba_libretro.so'},
                            {'cores': ['other.so']}, {'cores': [None]},
                            {'cores': ['mgba_libretro.so', 'mgba_libretro.so']}):
            with self.subTest(declaration=declaration), self.assertRaises(u.UpdateError):
                u.declared_cores(declaration)
        (self.system / 'gpsp_libretro.so').unlink()
        with self.assertRaises((u.UpdateError, FileNotFoundError)):
            u.Manager(self.root / 'bad-legacy', ENV).adopt(self.system, 'bad')

    def test_inventory_uses_file_modes_on_noexec_mount(self):
        binary = self.system / 'slot'
        binary.chmod(0o755)
        with patch.object(u.os, 'access', return_value=False):
            self.assertEqual(u.files(self.system)['slot']['mode'], 0o755)

    def test_success_confirm_and_manual_rollback(self):
        (self.system / 'slot').write_bytes(binary('new frontend'))
        self.install()
        self.assertEqual(self.manager.state()['current'], 'known-good')
        self.assertEqual(self.manager.select(), ('candidate', True))
        self.manager.confirm('candidate')
        self.assertEqual(self.manager.state()['previous'], 'known-good')
        self.manager.rollback()
        self.assertEqual(self.manager.select(), ('known-good', False))

    def test_component_replacement_removes_obsolete_system_files_only(self):
        # A legacy launcher asset is in the adopted base, absent in the new build.
        base_system = self.manager.revision('known-good') / 'System'
        (base_system / 'obsolete.txt').write_text('obsolete')
        meta = u.load(self.base)
        meta['files'] = u.files(base_system)
        u.atomic_json(self.base, meta)
        self.install()
        updated = self.manager.revision('candidate') / 'System'
        self.assertFalse((updated / 'obsolete.txt').exists())
        self.assertEqual((updated / 'mgba_libretro.so').read_bytes(), (base_system / 'mgba_libretro.so').read_bytes())

    def test_outer_corruption_rejected_without_pointer_change(self):
        p = self.make()
        expected = u.sha(p)
        p.write_bytes(p.read_bytes() + b'corrupt')
        with self.assertRaisesRegex(u.UpdateError, 'SHA-256'):
            self.manager.install(p, expected)
        self.assertIsNone(self.manager.state()['pending'])

    def test_wrong_device_runtime_base_and_migrations_rejected(self):
        changes = [lambda m: m['target'].update(device='rg353m'),
                   lambda m: m['runtime'].update(kernel='wrong'),
                   lambda m: m.update(base='old-base'),
                   lambda m: m['compat'].update(config=2),
                   lambda m: m['compat']['states'].update(mgba_libretro_so='different')]
        for i, change in enumerate(changes):
            with self.subTest(i=i):
                p = self.meta(self.make('invalid-' + str(i)), change)
                with self.assertRaises(u.UpdateError):
                    self.manager.install(p, u.sha(p))
                self.assertIsNone(self.manager.state()['pending'])

    def test_traversal_symlinks_duplicates_and_unlisted_files_rejected(self):
        for i, variant in enumerate(('traversal', 'symlink', 'duplicate', 'extra')):
            p = self.make('bad-archive-' + str(i))
            def change(rows):
                member = tarfile.TarInfo('../escaped' if variant == 'traversal' else 'extra')
                data = b'x'
                if variant == 'symlink':
                    member.type, member.linkname, data = tarfile.SYMTYPE, '/etc/passwd', b''
                if variant == 'duplicate':
                    member, data = rows[0]
                return rows + [(member, data)]
            self.rewrite(p, change)
            with self.assertRaises(u.UpdateError):
                self.manager.install(p, u.sha(p))
        self.assertFalse((self.root / 'escaped').exists())

    def test_inner_hash_and_architecture_rejected(self):
        p = self.make()
        def change(rows):
            return [(m, b'x' * len(data) if m.name == 'payload/slot' else data) for m, data in rows]
        self.rewrite(p, change)
        with self.assertRaisesRegex(u.UpdateError, 'Payload hash'):
            self.manager.install(p, u.sha(p))
        (self.system / 'slot').write_bytes(b'not an ELF')
        p = self.make('wrong-arch')
        with self.assertRaisesRegex(u.UpdateError, 'AArch64 ELF'):
            self.manager.install(p, u.sha(p))
        self.assertIsNone(self.manager.state()['pending'])

    def test_insufficient_space_preserves_active(self):
        p = self.make()
        with patch.object(u.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 1})()):
            with self.assertRaisesRegex(u.UpdateError, 'free system storage'):
                self.manager.install(p, u.sha(p))
        self.assertIsNone(self.manager.state()['pending'])

    def test_interrupt_during_copy_leaves_known_good(self):
        p = self.make()
        with patch.object(u.shutil, 'copyfileobj', side_effect=OSError('power interrupted')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.manager.install(p, u.sha(p))
        self.assertEqual(self.manager.select(), ('known-good', False))
        self.assertEqual(list(self.manager.revisions.glob('.install-*')), [])

    def test_interrupted_first_launch_rolls_back_on_next_boot(self):
        self.install()
        self.assertEqual(self.manager.select(), ('candidate', True))
        # Reconstructing Manager models restart after power loss, without confirmation.
        restarted = u.Manager(self.manager.root, ENV)
        self.assertEqual(restarted.select(), ('known-good', False))
        self.assertIsNone(restarted.state()['pending'])

    def test_interrupt_after_revision_rename_before_activation_keeps_old_pointer(self):
        p = self.make()
        original = u.atomic_json
        def interrupted(path, value):
            if Path(path) == self.manager.state_path:
                raise OSError('interrupted before pointer commit')
            return original(path, value)
        with patch.object(u, 'atomic_json', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'pointer commit'):
                self.manager.install(p, u.sha(p))
        self.assertTrue(self.manager.revision('candidate').is_dir())
        self.assertEqual(self.manager.select(), ('known-good', False))

    def test_damaged_confirmed_version_uses_retained_previous(self):
        self.install()
        self.manager.select()
        self.manager.confirm('candidate')
        (self.manager.revision('candidate') / 'System/slot').write_bytes(b'broken')
        self.assertEqual(self.manager.select(), ('known-good', False))
        self.assertIsNone(self.manager.state()['previous'])

    def test_corrupt_pending_revision_rolls_back(self):
        self.install()
        (self.manager.revision('candidate') / 'System/slot').write_bytes(b'broken')
        self.assertEqual(self.manager.select(), ('known-good', False))
        self.assertIsNone(self.manager.state()['pending'])

    def test_pending_update_rejects_second_install(self):
        self.install()
        p = self.make('second')
        with self.assertRaisesRegex(u.UpdateError, 'already pending'):
            self.manager.install(p, u.sha(p))

    def test_cross_component_payload_rejected(self):
        p = self.meta(self.make(), lambda m: m.update(kind='cores'))
        with self.assertRaisesRegex(u.UpdateError, 'component'):
            self.manager.install(p, u.sha(p))

    def test_changed_build_settings_contract_is_not_inherited_from_base(self):
        (self.system / 'update-contract.json').write_text('{"schema":1,"settings":2,"sram":1}')
        with self.assertRaisesRegex(u.UpdateError, 'settings/save migration'):
            self.make()

    def test_independent_core_update_and_explicit_state_contract(self):
        (self.system / 'mgba_libretro.so').write_bytes(binary('new core'))
        with self.assertRaisesRegex(u.UpdateError, 'verify state compatibility'):
            self.make(kind='cores')
        p = self.make(kind='cores', states_compatible=True)
        self.install(p)
        name, _ = self.manager.select()
        revision = self.manager.revision(name) / 'System'
        self.assertEqual((revision / 'slot').read_bytes(), (self.manager.revision('known-good') / 'System/slot').read_bytes())
        self.assertEqual((revision / 'mgba_libretro.so').read_bytes(), (self.system / 'mgba_libretro.so').read_bytes())
        self.manager.confirm(name)
        self.manager.rollback()

    def run_trial(self, script):
        (self.system / 'launch_frontend.sh').write_text(script)
        self.install()
        with patch.dict(os.environ, SLOT_ROOT=str(self.content)), patch.object(Path, 'is_mount', return_value=True), \
                patch.object(u, 'STARTUP_TIMEOUT', 0.7), patch.object(u, 'HEALTH_WINDOW', 0.15), \
                patch.object(u, 'RUN_DIRECTORY', self.root):
            return self.manager.run()

    def test_startup_crash_triggers_rollback(self):
        self.assertEqual(self.run_trial('#!/bin/sh\nexit 23\n'), 1)
        self.assertIsNone(self.manager.state()['pending'])
        self.assertEqual(self.manager.state()['current'], 'known-good')

    def test_no_render_heartbeat_times_out_and_rolls_back(self):
        # exec avoids leaving a shell grandchild after timeout.
        self.assertEqual(self.run_trial('#!/bin/sh\nexec sleep 20\n'), 1)
        self.assertEqual(self.manager.state()['current'], 'known-good')

    def test_render_heartbeat_confirms_candidate(self):
        script = '#!/bin/sh\nexec python3 -c \'import os,pathlib,time; p=pathlib.Path(os.environ["SLOT_UPDATE_READY"]); p.write_text("frame"); time.sleep(0.6)\'\n'
        self.assertEqual(self.run_trial(script), 0)
        self.assertEqual(self.manager.state()['current'], 'candidate')
        self.assertEqual(self.manager.state()['previous'], 'known-good')

    def test_disappearing_heartbeat_does_not_confirm_a_hung_frontend(self):
        script = '#!/bin/sh\nexec python3 -c \'import os,pathlib,time; p=pathlib.Path(os.environ["SLOT_UPDATE_READY"]); p.write_text("frame"); time.sleep(0.35); p.unlink(); time.sleep(2)\'\n'
        with patch.object(u, 'HEARTBEAT_AGE', 0.3):
            self.assertEqual(self.run_trial(script), 1)
        self.assertEqual(self.manager.state()['current'], 'known-good')

    def test_concurrent_update_rejected(self):
        other = u.Manager(self.manager.root, ENV)
        with self.manager.locked():
            with self.assertRaisesRegex(u.UpdateError, 'Another update'):
                with other.locked():
                    pass


if __name__ == '__main__':
    unittest.main()
