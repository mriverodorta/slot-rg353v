#!/usr/bin/env python3
"""Signed catch-up sessions, restart boundaries and delayed internet, host only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ota_fixtures', ROOT/'scripts/test-rg353v-ota.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
a = fixture.a


class Sessions(unittest.TestCase):
    signed = fixture.OTA.signed

    def setUp(self):
        fixture.OTA.setUp(self)
        self.session = a.UpdateSession(self.delivery)
        self.boot = 'boot-A'
        patch.object(a.UpdateSession, 'boot_id', side_effect=lambda: self.boot).start()
        self.now = 0.0
        patch.object(a.time, 'monotonic', side_effect=lambda: self.now).start()
        patch.object(a.time, 'sleep', side_effect=self.sleep).start()
        patch.object(a.UpdateSession, 'handoff').start()
        self.installed = {'id': 'v1', 'runtime': {'api': 1, 'os_build': 'os1', 'kernel': 'fixture'},
                          'files': {}, 'modules': None}
        self.session.begin('v2')

    def sleep(self, seconds):
        self.now += seconds

    def make_chain(self, kinds=('slot', 'slot', 'slot')):
        self.meta.pop('package', None)
        packages, self.payloads = [], {}
        runtime = self.installed['runtime']
        revision = self.installed['id']
        for index, kind in enumerate(kinds, 2):
            ident = 'v'+str(index)
            out = io.BytesIO()
            manifest = json.dumps({'id': ident, 'kind': kind}).encode()
            with tarfile.open(fileobj=out, mode='w:gz') as archive:
                member = tarfile.TarInfo('manifest.json'); member.size = len(manifest)
                archive.addfile(member, io.BytesIO(manifest))
            payload = out.getvalue()
            self.payloads[ident+'.tar.gz'] = payload
            package = {'id': ident, 'kind': kind, 'file': ident+'.tar.gz', 'size': len(payload),
                       'sha256': a.hashlib.sha256(payload).hexdigest()}
            if kind == 'os':
                package['requires'] = {'runtime': runtime, 'boot_files': {'SYSTEM': {'size': 3, 'sha256': 'a'*64}}}
                runtime = dict(runtime, os_build=ident)
                revision = 'os-'+ident
                package['provides'] = {'runtime': runtime, 'revision': revision,
                                       'boot_files': {'SYSTEM': {'size': 3, 'sha256': 'b'*64}}}
            else:
                package['requires'] = {'runtime': runtime, 'revision': revision,
                                       'inventory_sha256': a.u.inventory_hash({}), 'modules': None}
                revision = ident
                package['provides'] = {'runtime': runtime, 'revision': revision, 'modules': None, 'inventory_sha256': a.u.inventory_hash({})}
            packages.append(package)
        self.meta.update(schema=2, packages=packages, heads=[packages[-1]['provides']])
        self.signed_data = self.signed()
        return packages

    @contextlib.contextmanager
    def transport(self):
        def fetch(url, *_):
            return self.signed_data[1] if url.endswith('.sig') else self.signed_data[0]
        def opened(url, *_args, **_kwargs):
            return io.BytesIO(self.payloads[url.rsplit('/', 1)[1]])
        with patch.object(a, 'fetch', side_effect=fetch), patch.object(a, 'open_url', side_effect=opened), \
             patch.object(a.u, 'Manager') as manager:
            manager.return_value.state.side_effect = lambda: {'current': self.installed['id'], 'previous': None, 'pending': None}
            manager.return_value.verify_revision.side_effect = lambda _: dict(self.installed)
            yield

    def fake_apply(self, ident, *, before_install, staged, expected_sha):
        meta, path = self.delivery.download(ident)
        package = meta['package']
        self.assertEqual(a.u.sha(path), expected_sha)
        before_install(package)
        self.assertEqual(self.session.load()['phase'], 'applying')
        self.assertEqual(self.session.load()['step']['id'], ident)
        staged(package)
        self.assertEqual(self.session.load()['phase'], 'awaiting-health')
        if package['kind'] != 'os':
            self.installed.update(id=package['provides']['revision'], runtime=package['provides']['runtime'])

    def test_three_versions_behind_applies_signed_exact_base_steps_to_head(self):
        self.make_chain()
        with self.transport(), patch.object(self.delivery, 'apply', side_effect=self.fake_apply) as apply, \
             patch.object(self.session, 'activation', return_value='confirmed'):
            self.session.resume()
        self.assertEqual([c.args[0] for c in apply.call_args_list], ['v2', 'v3', 'v4'])
        self.assertEqual(self.installed['id'], 'v4')
        self.assertFalse(self.session.path.exists())
        record = a.u.load(self.delivery.root/'last-session.json')
        self.assertEqual(record['phase'], 'completed')
        self.assertEqual([s['id'] for s in record['completed']], ['v2', 'v3', 'v4'])
        self.assertEqual(self.delivery.status()['event'], 'up-to-date')
        self.assertEqual(len(list(self.delivery.root.glob('*.tar.gz'))), 1)

    def test_os_restart_resumes_from_durable_step_and_waits_27_seconds_for_internet(self):
        packages = self.make_chain(('slot', 'os', 'slot'))
        # Match the real old boot inventory without touching /flash.
        def applicable(package, installed, boot_files):
            if package['kind'] == 'os':
                return package['requires']['runtime'] == installed['runtime']
            return original(package, installed, boot_files)
        original = a.Delivery.applicable
        with self.transport(), patch.object(a.Delivery, 'applicable', side_effect=applicable), \
             patch.object(self.delivery, 'apply', side_effect=self.fake_apply) as apply, \
             patch.object(self.session, 'activation', side_effect=lambda step: 'reboot-required' if step['kind']=='os' else 'confirmed'):
            self.session.resume()
            self.assertEqual([c.args[0] for c in apply.call_args_list], ['v2', 'v3'])
            saved = self.session.load()
            self.assertEqual(saved['step']['id'], 'v3')
            self.assertEqual(saved['phase'], 'awaiting-health')
        # A new process/boot must use the persisted journal, not Python locals.
        self.boot = 'boot-B'
        self.installed.update(id='os-v3', runtime=packages[1]['provides']['runtime'])
        resumed = a.UpdateSession(self.delivery)
        check = self.delivery.check
        def delayed(*args, **kwargs):
            if self.now < 27:
                raise urllib.error.URLError('Wi-Fi is associating')
            return check(*args, **kwargs)
        with self.transport(), patch.object(self.delivery, 'check', side_effect=delayed), \
             patch.object(self.delivery, 'apply', side_effect=self.fake_apply) as apply, \
             patch.object(resumed, 'activation', return_value='confirmed'), \
             patch.object(resumed, 'restore_network') as restore, \
             patch.object(self.delivery, 'event', wraps=self.delivery.event) as events:
            resumed.resume()
            self.assertEqual([c.args[0] for c in apply.call_args_list], ['v4'])
            self.assertGreaterEqual(restore.call_count, 10)
            waits=[c.kwargs['seconds'] for c in events.call_args_list if c.args[0]=='waiting-network']
            self.assertIn(24, waits)
            self.assertNotIn('failed', [c.args[0] for c in events.call_args_list])
        self.assertFalse(resumed.path.exists())
        self.assertEqual(self.installed['id'], 'v4')

    def test_network_timeout_preserves_resumable_session_instead_of_failing_at_boot(self):
        with patch.object(self.delivery, 'check', side_effect=urllib.error.URLError('offline')), \
             patch.object(self.session, 'restore_network'), patch.object(self.delivery, 'apply') as apply:
            self.session.resume()
        apply.assert_not_called()
        self.assertEqual(self.session.load()['phase'], 'paused-network')
        self.assertGreaterEqual(self.now, a.NETWORK_WAIT)
        self.assertEqual(self.delivery.status()['event'], 'paused-network')

    def test_resume_restores_only_previous_transport_not_developer_or_remote_services(self):
        state = self.session.load(); state.update(connections=['wifi'], network_boot='boot-old')
        with patch.object(a.subprocess, 'run') as run:
            self.session.restore_network(state)
        commands = [c.args[0] for c in run.call_args_list]
        self.assertEqual(commands, [['/usr/bin/slot-services', 'wifi', 'on'],
                                   ['systemctl', 'start', 'network-base.service', 'openssl-config.service']])
        self.assertEqual(self.session.load()['network_boot'], self.boot)
        with patch.object(a.subprocess, 'run') as run:
            self.session.restore_network(state)
        run.assert_not_called()

    def test_usb_only_session_restores_usb_without_enabling_wifi_or_ssh(self):
        state = self.session.load(); state.update(connections=['usb'], network_boot='boot-old')
        with patch.object(a.subprocess, 'run') as run:
            self.session.restore_network(state)
        self.assertEqual(run.call_args_list[0].args[0], ['systemctl', 'start', 'slot-usb-network.service'])
        self.assertNotIn('wifi', repr(run.call_args_list))

    def test_rollback_stops_all_later_updates_and_cannot_retry_itself_on_next_boot(self):
        self.make_chain()
        with self.transport(), patch.object(self.delivery, 'apply', side_effect=self.fake_apply) as apply, \
             patch.object(self.session, 'activation', return_value='rolled-back'):
            self.session.resume()
            self.session.resume()
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(self.session.load()['phase'], 'failed')
        self.assertEqual(self.delivery.status()['event'], 'rolled-back')

    def test_unknown_base_is_not_up_to_date_and_no_payload_is_downloaded(self):
        self.make_chain(); self.installed['id'] = 'unsupported'
        with self.transport(), patch.object(self.delivery, 'apply') as apply:
            self.session.resume()
        apply.assert_not_called()
        self.assertEqual(self.delivery.status()['event'], 'no-path')
        self.assertEqual(self.session.load()['phase'], 'paused')

    def test_catalog_cycle_is_stopped_before_reapplying_a_completed_target(self):
        package = {'id': 'v2', 'kind': 'slot', 'file': 'v2.tar.gz', 'size': 1, 'sha256': 'a'*64}
        state = self.session.load(); state.update(expected='', completed=[{k:package[k] for k in ('id','kind','sha256')}])
        self.session.save(state)
        with patch.object(self.session, 'wait_network', return_value=({'package':package}, 'https://example/v2.tar.gz')), \
             patch.object(self.delivery, 'apply') as apply:
            with self.assertRaisesRegex(a.u.UpdateError, 'cycle'):
                self.session.resume()
        apply.assert_not_called()

    def test_signature_failure_is_not_retried_as_wifi_connecting(self):
        with patch.object(self.delivery, 'check', side_effect=a.u.UpdateError('publisher signature is not trusted')) as check:
            with self.assertRaisesRegex(a.u.UpdateError, 'signature'):
                self.session.resume()
        self.assertEqual(check.call_count, 1)
        self.assertEqual(self.now, 0)
        self.assertEqual(self.session.load()['phase'], 'paused')

    def test_cancel_during_startup_health_wait_finishes_health_before_stopping(self):
        self.make_chain()
        state = self.session.load(); state.update(step=dict(self.meta['packages'][0], boot=self.boot), phase='awaiting-health')
        self.session.save(state)
        a.u.atomic_json(self.session.cancel_path, {'id':state['id']})
        with patch.object(self.session, 'activation', side_effect=['pending','confirmed']) as activation, \
             patch.object(self.delivery, 'apply') as apply:
            self.session.resume()
        self.assertEqual(activation.call_count, 2)
        apply.assert_not_called()
        self.assertFalse(self.session.path.exists())
        self.assertEqual(a.u.load(self.delivery.root/'last-session.json')['phase'], 'cancelled')

    def test_duplicate_boot_request_never_starts_another_worker(self):
        with patch.object(a, 'job_active', return_value=True), patch.object(a.subprocess, 'run') as run:
            a.request_job(self.delivery, 'resume', '')
        run.assert_not_called()

    def test_cancel_a_paused_session_archives_it_without_stopping_services(self):
        with patch.object(a, 'job_active', return_value=False), patch.object(a.subprocess, 'run') as run:
            a.request_job(self.delivery, 'cancel', '')
        run.assert_not_called()
        self.assertFalse(self.session.path.exists())

    def test_apply_checksum_can_change_before_preflight_but_not_before_service_stop(self):
        package = dict(self.meta['package'])
        with patch.object(self.delivery, 'download', return_value=(self.meta, self.root/'unused')), \
             patch.object(a.subprocess, 'run') as run:
            with self.assertRaisesRegex(a.u.UpdateError, 'changed during'):
                self.delivery.apply('fixture', expected_sha='f'*64)
        run.assert_not_called()

    def test_worker_activation_record_is_durable_before_reboot_command(self):
        package = dict(self.meta['package'])
        state = self.session.load()
        def before(descriptor):
            state['step'] = dict(descriptor, boot=self.boot)
            self.session.save(state, 'applying')
        def staged(_):
            self.session.save(state, 'awaiting-health')
        def command(args, **_):
            if args == ['systemctl','reboot']:
                self.assertEqual(self.session.load()['phase'], 'awaiting-health')
                self.assertEqual(self.session.load()['step']['id'], package['id'])
            return subprocess.CompletedProcess(args, 0)
        with patch.object(self.delivery, 'download', return_value=(self.meta, self.root/'package')), \
             patch.object(a, 'shelf_and_power'), patch.object(a, 'require_shelf'), \
             patch.object(a, 'module') as module, patch.object(a.subprocess, 'run', side_effect=command) as run:
            self.delivery.apply(package['id'], before_install=before, staged=staged, expected_sha=package['sha256'])
        self.assertIn(['systemctl','reboot'], [c.args[0] for c in run.call_args_list])

    def test_network_failure_before_install_has_no_activation_to_reconcile(self):
        self.make_chain()
        with self.transport(), patch.object(self.delivery, 'apply', side_effect=OSError('download disconnected')):
            with self.assertRaisesRegex(OSError, 'disconnected'):
                self.session.resume()
        self.assertIsNone(self.session.load()['step'])
        self.assertEqual(self.session.load()['phase'], 'paused')

    def test_signed_three_step_chain_uses_real_revision_install_and_confirmation(self):
        spec = importlib.util.spec_from_file_location('update_transactions', ROOT/'scripts/test-rg353v-updates.py')
        transactions = importlib.util.module_from_spec(spec); spec.loader.exec_module(transactions)
        case = transactions.Updates(); case.setUp()
        try:
            actual = a.u.Manager(case.root/'actual', transactions.ENV)
            actual.adopt(case.system, 'known-good')
            packages = []
            for ident in ('v2', 'v3', 'v4'):
                (case.system/'slot').write_bytes(transactions.binary(ident))
                package = case.make(ident, delta=True)
                packages.append(package)
                case.install(package)
                selected, trial = case.manager.select()
                self.assertTrue(trial)
                case.manager.confirm(selected)
                case.base = case.manager.revision(ident)/'revision.json'
            subprocess.run(['python3', str(ROOT/'scripts/sign-rg353v-release.py'), '--catalog',
                            *map(str, packages), '--key', str(self.private), '--sequence', '1'],
                           check=True, capture_output=True)
            self.meta = a.u.load(case.root/'release.json')
            self.signed_data = self.signed()
            payloads = {p.name:p.read_bytes() for p in packages}
            original_manager, original_run = a.u.Manager, subprocess.run
            def manager(root, *args, **kwargs):
                return actual if str(root)=='/storage/slot-manager' else original_manager(root, *args, **kwargs)
            def command(args, **kwargs):
                if args[:2] == ['systemctl', 'start']:
                    selected, trial = actual.select()
                    self.assertTrue(trial)
                    actual.confirm(selected)
                if args[0] == 'systemctl':
                    return subprocess.CompletedProcess(args, 0)
                return original_run(args, **kwargs)
            def fetch(url, *_):
                return self.signed_data[1] if url.endswith('.sig') else self.signed_data[0]
            with patch.object(a.u, 'Manager', side_effect=manager), patch.object(a, 'fetch', side_effect=fetch), \
                 patch.object(a, 'open_url', side_effect=lambda url, *_: io.BytesIO(payloads[url.rsplit('/',1)[1]])), \
                 patch.object(a, 'shelf_and_power'), patch.object(a, 'require_shelf'), \
                 patch.object(a.subprocess, 'run', side_effect=command):
                self.session.resume()
            self.assertEqual(actual.state()['current'], 'v4')
            self.assertEqual(actual.state()['previous'], 'v3')
            self.assertIsNone(actual.state()['pending'])
            actual.verify_revision('v4')
            self.assertFalse(self.session.path.exists())
            self.assertEqual((actual.revision('v4')/'System/slot').read_bytes(), transactions.binary('v4'))
        finally:
            case.tearDown()

    def test_final_version_name_with_different_files_is_not_up_to_date(self):
        self.make_chain(); self.installed['id'] = 'v4'
        self.installed['files'] = {'changed': {'sha256': 'c'*64, 'size': 1, 'mode': 0o644}}
        with self.transport(), patch.object(self.delivery, 'apply') as apply:
            self.session.resume()
        apply.assert_not_called()
        self.assertEqual(self.delivery.status()['event'], 'no-path')

    def test_completed_session_does_not_restart_network_checks_on_later_boots(self):
        self.make_chain()
        with self.transport(), patch.object(self.delivery, 'apply', side_effect=self.fake_apply), \
             patch.object(self.session, 'activation', return_value='confirmed'):
            self.session.resume()
        self.boot = 'boot-C'
        with patch.object(self.delivery, 'check') as check, patch.object(a.subprocess, 'run') as run:
            a.UpdateSession(self.delivery).resume()
        check.assert_not_called(); run.assert_not_called()

    def test_stop_during_download_does_not_begin_installation(self):
        self.make_chain()
        def download_then_cancel(ident, **kwargs):
            a.u.atomic_json(self.session.cancel_path, {'id': self.session.load()['id']})
            self.fake_apply(ident, **kwargs)
        with self.transport(), patch.object(self.delivery, 'apply', side_effect=download_then_cancel), \
             patch.object(self.session, 'activation') as activation:
            self.session.resume()
        activation.assert_not_called()
        self.assertEqual(self.installed['id'], 'v1')
        self.assertFalse(self.session.path.exists())
        self.assertEqual(a.u.load(self.delivery.root/'last-session.json')['phase'], 'cancelled')

    def test_cancel_pending_health_resumes_confirmation_without_killing_the_worker(self):
        self.make_chain(); state=self.session.load()
        state.update(phase='paused', step=dict(self.meta['packages'][0], boot=self.boot))
        self.session.save(state)
        with patch.object(a, 'job_active', return_value=False), patch.object(a.subprocess, 'run') as run:
            a.request_job(self.delivery, 'cancel', '')
        self.assertTrue(self.session.path.exists())
        self.assertTrue(self.session.cancelled(state))
        command=run.call_args.args[0]
        self.assertIn('systemd-inhibit', command)
        self.assertIn('resume', command)
        self.assertNotIn('stop', command)

    def test_declared_final_head_stops_even_if_older_edges_remain_in_catalog(self):
        self.make_chain()
        self.meta['heads']=[dict(runtime=self.installed['runtime'], revision='v1', modules=None,
                                 inventory_sha256=a.u.inventory_hash(self.installed['files']))]
        self.signed_data=self.signed()
        with self.transport(), patch.object(self.delivery, 'apply') as apply:
            self.session.resume()
        apply.assert_not_called()
        self.assertFalse(self.session.path.exists())
        self.assertEqual(self.delivery.status()['event'], 'up-to-date')


if __name__ == '__main__':
    unittest.main()
