#!/usr/bin/env python3
"""Execute the normal-boot guard against mutation, trials and recovery fixtures."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'ports/rg353v/rocknix/slot-rg353v'
loader = importlib.machinery.SourceFileLoader('native_updater', str(PKG / 'scripts/slot-update'))
spec = importlib.util.spec_from_loader(loader.name, loader)
u = importlib.util.module_from_spec(spec)
loader.exec_module(u)


class NormalBoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native_dir = tempfile.TemporaryDirectory()
        cls.verifier = os.environ.get('SLOT_VERIFY')
        if not cls.verifier:
            cls.verifier = str(Path(cls.native_dir.name) / 'slot-verify')
            flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'openssl'], text=True)
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'ports/rg353v/rocknix/slot-startup-profile/src/slot-verify.c'),
                            *shlex.split(flags), '-o', cls.verifier], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.native_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.environment = {'api': 1, 'os_build': 'fixture', 'kernel': platform.release()}
        self.manager = u.Manager(self.root / 'manager')
        self.system = self.manager.revisions / 'good' / 'System'
        self.system.mkdir(parents=True)
        (self.system / 'slot').write_bytes(b'frontend')
        (self.system / 'slot').chmod(0o755)
        (self.system / 'launch_frontend.sh').write_text('echo FAST_FRONTEND\n')
        u.atomic_json(self.system.parent / 'revision.json', {
            'files': u.files(self.system), 'runtime': self.environment})
        u.atomic_json(self.manager.state_path, {'schema': 1, 'current': 'good', 'previous': None, 'pending': None})
        self.runtime = self.root / 'os-release'
        self.runtime.write_text('BUILD_ID=fixture\n')
        self.addCleanup(patch.stopall)
        patch.object(u, 'runtime', return_value=self.environment).start()
        patch.object(u, 'RUNTIME_FILES', [self.runtime]).start()
        with self.manager.locked():
            self.manager.cache_normal_boot('good')
        script = (PKG / 'scripts/slot-normal-start').read_text()
        self.script = script.replace('/storage/slot-manager', str(self.manager.root)).replace('/usr/bin/slot-verify', self.verifier)
        self.script = self.script.replace('exec /usr/bin/slot-update run', 'echo FULL_UPDATER; exit 42')

    def run_guard(self):
        # Replace the recipe fallback too, and recertify only this test helper.
        recipe = self.manager.root / 'normal-boot-v2.sh'
        original = recipe.read_text()
        edited = original.replace('exec /usr/bin/slot-update run', 'echo FULL_UPDATER; exit 42')
        if original != edited:
            old = u.sha(recipe)
            recipe.write_text(edited)
            manifest = self.manager.root / 'normal-boot-v2.sha256'
            if manifest.exists():
                manifest.write_text(manifest.read_text().replace(old, u.sha(recipe)))
        return subprocess.run(['sh', '-c', self.script], env=dict(os.environ, SLOT_ROOT=str(self.root)),
                              text=True, capture_output=True)

    def assert_slow(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        self.assertNotIn('FAST_FRONTEND', result.stdout)

    def test_unchanged_verified_revision_executes_without_python(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('FAST_FRONTEND', result.stdout)

    def test_pending_update_cannot_use_confirmed_recipe(self):
        state = self.manager.state()
        state['pending'] = {'id': 'trial', 'attempts': 0}
        u.atomic_json(self.manager.state_path, state)
        self.assert_slow()

    def test_module_and_feature_record_changes_invalidate_the_native_recipe(self):
        records=[self.root/'modules-v1.json',self.root/'features-v1']
        for p in records:p.write_text('original installed selection')
        with patch.object(u,'runtime_files',return_value=(self.runtime,*records)):
            self.manager.cache_normal_boot('good')
        self.assertEqual(self.run_guard().returncode,0)
        records[0].write_text('changed selection');self.assert_slow()
        records[0].write_text('original installed selection');self.assertEqual(self.run_guard().returncode,0)
        records[1].unlink();self.assert_slow()

    def test_runtime_change_requires_full_validation(self):
        self.runtime.write_text('BUILD_ID=new\n')
        self.assert_slow()

    def test_corruption_requires_existing_rollback_path(self):
        (self.system / 'slot').write_bytes(b'corrupt')
        self.assert_slow()

    def test_changed_executable_mode_is_not_hidden_by_matching_hash(self):
        (self.system / 'slot').chmod(0o644)
        self.assert_slow()

    def test_added_file_requires_full_inventory_check(self):
        (self.system / 'extra').write_text('extra')
        self.assert_slow()

    def test_same_bytes_through_symlink_are_rejected(self):
        original = self.system / 'slot'
        target = self.root / 'copy'
        target.write_bytes(original.read_bytes()); target.chmod(0o755)
        original.unlink(); original.symlink_to(target)
        self.assert_slow()

    def test_added_directory_symlink_is_rejected(self):
        (self.system / 'extra').symlink_to(self.root, target_is_directory=True)
        self.assert_slow()

    def test_changed_recipe_and_interrupted_publication_are_rejected(self):
        (self.manager.root / 'normal-boot-v2.sh').write_text('echo bad\n')
        self.assert_slow()

    def recertify_inventory(self, text):
        inventory = self.manager.root / 'normal-boot-v2.inventory'
        previous = u.sha(inventory)
        inventory.write_text(text)
        manifest = self.manager.root / 'normal-boot-v2.sha256'
        manifest.write_text(manifest.read_text().replace(previous, u.sha(inventory)))

    def test_changed_kernel_requires_full_validation(self):
        inventory = self.manager.root / 'normal-boot-v2.inventory'
        self.recertify_inventory(inventory.read_text().replace(platform.release(), 'wrong-kernel'))
        self.assert_slow()

    def test_truncated_or_duplicate_inventory_fails_closed(self):
        inventory = self.manager.root / 'normal-boot-v2.inventory'
        original = inventory.read_text()
        self.recertify_inventory(original + original.splitlines()[-1] + '\n')
        self.assert_slow()
        self.recertify_inventory(original.rsplit('\n', 2)[0] + '\n')
        self.assert_slow()

    def test_parent_path_in_inventory_is_rejected(self):
        inventory = self.manager.root / 'normal-boot-v2.inventory'
        self.recertify_inventory(inventory.read_text().replace('755 slot', '755 ../slot'))
        self.assert_slow()

    def test_removed_revision_metadata_checksum_fails_closed(self):
        manifest = self.manager.root / 'normal-boot-v2.sha256'
        manifest.write_text(''.join(l for l in manifest.read_text().splitlines(True) if 'revision.json' not in l))
        self.assert_slow()

    def test_corrupt_inventory_without_matching_checksum_fails_closed(self):
        (self.manager.root / 'normal-boot-v2.inventory').write_text('incomplete')
        self.assert_slow()

    def test_revision_directory_symlink_is_rejected(self):
        moved = self.root / 'moved'
        self.system.rename(moved)
        self.system.symlink_to(moved, target_is_directory=True)
        self.assert_slow()

    def test_missing_checksum_list_uses_full_updater(self):
        (self.manager.root / 'normal-boot-v2.sha256').unlink()
        self.assert_slow()

    def source_archive(self, executable=False):
        path = self.system / 'licenses/slot-source.tar.gz'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'retained source archive')
        path.chmod(0o755 if executable else 0o644)
        meta = u.load(self.system.parent / 'revision.json')
        meta['files'] = u.files(self.system)
        u.atomic_json(self.system.parent / 'revision.json', meta)
        with self.manager.locked():
            self.manager.cache_normal_boot('good')
        return path

    def test_only_source_archive_hash_is_deferred_and_full_audit_detects_damage(self):
        archive = self.source_archive()
        archive.write_bytes(b'damaged archive')
        self.assertEqual(self.run_guard().returncode, 0)
        strict = subprocess.run([self.verifier, '--all', str(self.manager.root)])
        self.assertNotEqual(strict.returncode, 0)
        self.assertEqual(self.manager.audit_normal_boot(self.verifier)['status'], 'failed')
        self.assertTrue((self.manager.root / 'normal-boot-audit.failed').exists())
        self.assert_slow()
        # A full successful cache repair clears the durable failure marker.
        archive.write_bytes(b'retained source archive')
        with self.manager.locked():
            self.manager.cache_normal_boot('good')
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertFalse((self.manager.root / 'normal-boot-audit.failed').exists())

    def test_missing_symlinked_executable_or_unlisted_archive_never_defers(self):
        for change in ('missing', 'symlink', 'executable', 'unlisted'):
            with self.subTest(change=change):
                archive = self.source_archive()
                if change == 'missing':
                    archive.unlink()
                elif change == 'symlink':
                    target = self.root / 'archive-copy'
                    target.write_bytes(archive.read_bytes())
                    archive.unlink(); archive.symlink_to(target)
                elif change == 'executable':
                    archive.chmod(0o755)
                else:
                    manifest = self.manager.root / 'normal-boot-v2.sha256'
                    manifest.write_text(''.join(l for l in manifest.read_text().splitlines(True)
                                                if not l.rstrip().endswith(str(archive))))
                self.assert_slow()
                archive.unlink(missing_ok=True)

    def test_executable_source_archive_and_other_license_content_are_checked(self):
        archive = self.source_archive(executable=True)
        archive.write_bytes(b'corrupt executable archive')
        self.assert_slow()
        archive.unlink()
        self.source_archive()
        license_file = self.system / 'licenses/LICENSE'
        license_file.write_text('license')
        meta = u.load(self.system.parent / 'revision.json')
        meta['files'] = u.files(self.system)
        u.atomic_json(self.system.parent / 'revision.json', meta)
        self.manager.cache_normal_boot('good')
        license_file.write_text('changed')
        self.assert_slow()

    def test_audit_does_not_mark_pending_trial_or_updater_contention_as_corruption(self):
        self.source_archive()
        with self.manager.locked():
            self.assertEqual(self.manager.audit_normal_boot(self.verifier)['reason'], 'updater-busy')
        state = self.manager.state(); state['pending'] = {'id': 'trial', 'attempts': 0}
        u.atomic_json(self.manager.state_path, state)
        self.assertEqual(self.manager.audit_normal_boot(self.verifier)['reason'], 'pending-trial')
        self.assertFalse((self.manager.root / 'normal-boot-audit.failed').exists())

    def test_successful_background_audit_and_broken_failure_marker(self):
        self.source_archive()
        self.assertEqual(self.manager.audit_normal_boot(self.verifier)['status'], 'passed')
        (self.manager.root / 'normal-boot-audit.failed').symlink_to(self.root / 'missing')
        self.assert_slow()

    def sealed_cores(self):
        for name in sorted(u.CORES):
            path = self.system / name
            path.write_bytes(b'fixture core: ' + name.encode())
            path.chmod(0o755)
        (self.system / 'core-verification-v1').write_text('SLOT-CORE-SEALED-1\n')
        meta = u.load(self.system.parent / 'revision.json')
        meta['compat'] = u.contract(self.system)
        meta['files'] = u.files(self.system)
        u.atomic_json(self.system.parent / 'revision.json', meta)
        self.manager.cache_normal_boot('good')
        return self.system / 'mgba_libretro.so'

    def test_opt_in_core_hash_waits_but_full_audit_and_launch_reject_damage(self):
        core = self.sealed_cores()
        expected = u.sha(core)
        core.write_bytes(b'damaged')
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertNotEqual(subprocess.run([self.verifier, '--all', str(self.manager.root)]).returncode, 0)
        self.assert_snapshot(core, expected, success=False)
        self.assertEqual(self.manager.audit_normal_boot(self.verifier)['status'], 'failed')
        self.assert_slow()

    def test_legacy_cores_still_checked_before_shelf_and_marker_is_bound(self):
        core = self.sealed_cores()
        marker = self.system / 'core-verification-v1'
        marker.write_text('corrupt')
        self.assert_slow()
        marker.unlink()
        meta = u.load(self.system.parent / 'revision.json'); meta['files'] = u.files(self.system)
        u.atomic_json(self.system.parent / 'revision.json', meta)
        self.manager.cache_normal_boot('good')
        core.write_bytes(b'damaged')
        self.assert_slow()
        self.assertNotIn('export SLOT_CORE_HASHES=', (self.manager.root / 'normal-boot-v2.sh').read_text())

    def test_opt_in_core_inventory_modes_and_links_cannot_be_deferred(self):
        for change in ('missing', 'symlink', 'mode', 'unlisted'):
            with self.subTest(change=change):
                core = self.sealed_cores()
                if change == 'missing': core.unlink()
                elif change == 'symlink':
                    target = self.root / 'core-copy'; target.write_bytes(core.read_bytes()); target.chmod(0o755)
                    core.unlink(); core.symlink_to(target)
                elif change == 'mode': core.chmod(0o644)
                else:
                    manifest = self.manager.root / 'normal-boot-v2.sha256'
                    manifest.write_text(''.join(l for l in manifest.read_text().splitlines(True) if not l.rstrip().endswith(str(core))))
                self.assert_slow()
                core.unlink(missing_ok=True)

    def assert_snapshot(self, core, expected, success):
        import fcntl
        fd = os.memfd_create('core-test', os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
        try:
            result = subprocess.run([self.verifier, '--core', expected, str(core)], stdout=fd)
            self.assertEqual(result.returncode == 0, success)
            if success:
                seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
                self.assertEqual(fcntl.fcntl(fd, fcntl.F_GET_SEALS), seals)
                os.lseek(fd, 0, os.SEEK_SET)
                copied = os.read(fd, 100000)
                self.assertEqual(copied, core.read_bytes())
                core.write_bytes(b'replaced after check')
                os.lseek(fd, 0, os.SEEK_SET)
                self.assertEqual(os.read(fd, 100000), copied)
                with self.assertRaises(OSError): os.write(fd, b'changed')
                with self.assertRaises(OSError): os.ftruncate(fd, 0)
        finally: os.close(fd)

    def test_verified_snapshot_is_exact_sealed_and_survives_source_replacement(self):
        core = self.sealed_cores()
        self.assert_snapshot(core, u.sha(core), success=True)

    def test_snapshot_rejects_bad_hash_symlink_mode_name_and_regular_output(self):
        core = self.sealed_cores(); expected = u.sha(core)
        for bad in ('', 'a'*63, 'A'*64, '0'*64): self.assert_snapshot(core, bad, success=False)
        core.chmod(0o644); self.assert_snapshot(core, expected, success=False); core.chmod(0o755)
        other = core.with_name('other.so'); other.write_bytes(core.read_bytes()); other.chmod(0o755)
        self.assert_snapshot(other, expected, success=False)
        target = self.root / 'core-original'; core.rename(target); core.symlink_to(target)
        self.assert_snapshot(core, expected, success=False)
        core.unlink(); target.rename(core)
        with tempfile.TemporaryFile() as output:
            self.assertNotEqual(subprocess.run([self.verifier, '--core', expected, str(core)], stdout=output).returncode, 0)
            self.assertEqual(output.tell(), 0)

    def test_declared_single_core_recipe_and_full_audit_accept_only_that_core(self):
        for core in sorted(u.CORES):
            with self.subTest(core=core):
                self.sealed_cores()
                for omitted in u.CORES - {core}: (self.system / omitted).unlink()
                u.atomic_json(self.system / 'update-contract.json',
                              {'schema': 1, 'settings': 1, 'sram': 1, 'cores': [core]})
                meta = u.load(self.system.parent / 'revision.json')
                meta['compat'] = u.contract(self.system); meta['files'] = u.files(self.system)
                u.atomic_json(self.system.parent / 'revision.json', meta)
                self.manager.cache_normal_boot('good')
                recipe = (self.manager.root / 'normal-boot-v2.sh').read_text()
                self.assertIn(core + '=' + u.sha(self.system / core), recipe)
                for omitted in u.CORES - {core}: self.assertNotIn(omitted + '=', recipe)
                self.assertEqual(self.run_guard().returncode, 0)
                self.assertEqual(subprocess.run([self.verifier, '--all', str(self.manager.root)]).returncode, 0)
                (self.system / core).unlink()
                self.assert_slow()
                # Clear declaration so the next fixture starts with the legacy pair.
                (self.system / 'update-contract.json').unlink()

    def test_recipe_exports_hashes_from_revision_and_rejects_incomplete_contract(self):
        self.sealed_cores()
        recipe = (self.manager.root / 'normal-boot-v2.sh').read_text()
        for name in u.CORES:
            self.assertIn(name + '=' + u.sha(self.system / name), recipe)
        (self.system / 'gpsp_libretro.so').unlink()
        meta = u.load(self.system.parent / 'revision.json'); meta['files'] = u.files(self.system)
        u.atomic_json(self.system.parent / 'revision.json', meta)
        with self.assertRaises(u.UpdateError): self.manager.cache_normal_boot('good')


class OSBoot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cmdline = self.root / 'cmdline'
        self.cmdline.write_text('quiet')
        self.script = (PKG / 'scripts/slot-os-boot').read_text().replace('/storage/slot-os-updates', str(self.root))
        self.script = self.script.replace('/proc/cmdline', str(self.cmdline))
        self.script = self.script.replace('exec /usr/bin/slot-os-update "$@"', 'echo FULL_OS_GUARD; exit 42')

    def run_guard(self):
        return subprocess.run(['sh', '-c', self.script], capture_output=True, text=True)

    def confirmed(self):
        self.cmdline.write_text('quiet SLOT_OS_ID=confirmed')
        (self.root / 'state.json').write_text('{"transaction":"confirmed"}')
        (self.root / 'normal-boot.id').write_text('confirmed\n' + platform.release() + '\n')
        paths = [self.root / name for name in ('state.json', 'normal-boot.id')]
        (self.root / 'normal-boot.sha256').write_text(''.join(f'{u.sha(p)}  {p}\n' for p in paths))

    def test_factory_without_transaction_avoids_python(self):
        self.assertEqual(self.run_guard().returncode, 0)

    def test_confirmed_state_avoids_python_but_changed_pointer_does_not(self):
        self.confirmed()
        self.assertEqual(self.run_guard().returncode, 0)
        (self.root / 'state.json').write_text('{"transaction":"pending"}')
        self.assertEqual(self.run_guard().returncode, 42)

    def test_pending_first_boot_requires_full_guard(self):
        (self.root / 'state.json').write_text('{"transaction":"pending"}')
        self.assertEqual(self.run_guard().returncode, 42)

    def test_malformed_stamp_falls_back_instead_of_stopping_boot(self):
        self.confirmed()
        (self.root / 'normal-boot.id').write_text('truncated')
        self.assertEqual(self.run_guard().returncode, 42)

    def test_booting_previous_os_requires_rollback_association(self):
        self.confirmed()
        self.cmdline.write_text('quiet SLOT_OS_ID=previous')
        self.assertEqual(self.run_guard().returncode, 42)


if __name__ == '__main__':
    unittest.main()
