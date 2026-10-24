#!/usr/bin/env python3
"""Signed release trust, anti-replay, URL, and download corruption regressions."""
import importlib.machinery
import importlib.util
import io
import shutil
import sys
import contextlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('ota', str(ROOT / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-ota'))
spec = importlib.util.spec_from_loader(loader.name, loader)
a = importlib.util.module_from_spec(spec)
loader.exec_module(a)


class OTA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private, self.public = self.root / 'key', self.root / 'key.pub'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(self.private)], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(self.private), '-pubout', '-out', str(self.public)], check=True, capture_output=True)
        self.config = self.root / 'config'
        a.u.atomic_json(self.config, {'url': 'http://127.0.0.1/release.json', 'development_http': True})
        patch.object(a.time, 'sleep', return_value=None).start()
        self.addCleanup(patch.stopall)
        self.delivery = a.Delivery(self.root / 'downloads', self.config, [self.public])
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w:gz') as archive:
            b = b'{"id":"fixture","kind":"os"}'
            t = tarfile.TarInfo('manifest.json')
            t.size = len(b)
            archive.addfile(t, io.BytesIO(b))
        self.payload = raw.getvalue()
        now = int(time.time())
        self.meta = {'schema': 1, 'target': {'device': 'rg353v', 'arch': 'aarch64'},
                     'sequence': 1, 'issued': now, 'expires': now + 3600,
                     'package': {'id': 'fixture', 'kind': 'os', 'file': 'fixture.tar.gz',
                                 'size': len(self.payload), 'sha256': a.hashlib.sha256(self.payload).hexdigest()}}

    def signed(self):
        raw = json.dumps(self.meta).encode()
        source, signature = self.root / 'release', self.root / 'signature'
        source.write_bytes(raw)
        subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(self.private),
                        '-in', str(source), '-out', str(signature)], check=True, capture_output=True)
        return raw, signature.read_bytes()

    def check(self):
        with patch.object(a, 'fetch', side_effect=self.signed()):
            return self.delivery.check()

    def catalog(self):
        installed={'id':'base','runtime':{'api':1,'os_build':'fixture','kernel':'fixture'},'files':{},'modules':None}
        descriptor=dict(self.meta['package'],kind='slot',requires={
            'runtime':installed['runtime'],'revision':'base','inventory_sha256':a.u.inventory_hash({}),'modules':None})
        self.meta.pop('package');self.meta.update(schema=2,packages=[descriptor])
        return installed,descriptor

    def check_catalog(self,installed):
        with patch.object(a.u,'Manager') as manager:
            manager.return_value.state.return_value={'current':installed['id']}
            manager.return_value.verify_revision.return_value=installed
            return self.check()

    def test_factory_feed_is_used_without_a_local_override(self):
        factory = self.root / 'factory-feed.json'
        expected = {'url': 'https://github.com/owner/repo/releases/latest/download/release.json',
                    'development_http': False}
        a.u.atomic_json(factory, expected)
        self.config.unlink()
        with patch.object(a, 'DEFAULT_CONFIG', factory):
            self.assertEqual(self.delivery.configuration(), expected)
            a.u.atomic_json(self.config, {'url': 'https://custom.example/release.json'})
            self.assertEqual(self.delivery.configuration()['url'], 'https://custom.example/release.json')
            self.config.write_text('invalid JSON')
            with self.assertRaises(ValueError):
                self.delivery.configuration()

    def test_signed_empty_initial_catalog_is_up_to_date_without_a_download(self):
        installed, _ = self.catalog()
        self.meta['packages'] = []
        meta, url = self.check_catalog(installed)
        self.assertEqual(meta['package'], {})
        self.assertIsNone(url)
        self.assertEqual(self.delivery.status()['event'], 'up-to-date')
        self.assertEqual(a.u.load(self.delivery.root / 'accepted.json')['sequence'], 1)

    def test_signer_can_publish_an_empty_initial_catalog(self):
        subprocess.run(['python3', str(ROOT/'scripts/sign-rg353v-release.py'), '--catalog',
                        '--output-dir', str(self.root), '--key', str(self.private),
                        '--sequence', '1'], check=True, capture_output=True)
        raw = (self.root/'release.json').read_bytes()
        self.assertEqual(json.loads(raw)['packages'], [])
        a.verify_signature(raw, (self.root/'release.json.sig').read_bytes(), [self.public])

    def test_catalog_selects_only_exact_base_and_module_selection(self):
        installed,p=self.catalog()
        meta,url=self.check_catalog(installed)
        self.assertEqual(meta['package'],p)
        self.assertTrue(url.endswith('/fixture.tar.gz'))
        for field,value in [('revision','another'),('inventory_sha256','0'*64),('modules',['ssh'])]:
            previous=p['requires'][field];p['requires'][field]=value
            self.meta['sequence']+=1
            meta,url=self.check_catalog(installed)
            self.assertEqual(meta['package'],{});self.assertIsNone(url)
            self.assertEqual(self.delivery.status()['event'],'no-path')
            p['requires'][field]=previous

    def test_catalog_prefers_smallest_matching_variant_and_keeps_publisher_order(self):
        installed,p=self.catalog()
        smaller=dict(p,file='small.tar.gz',size=p['size']-1)
        other=dict(p,id='next-step',file='next.tar.gz',size=1)
        self.meta['packages']=[p,smaller,other]
        meta,_=self.check_catalog(installed)
        self.assertEqual(meta['package']['file'],'small.tar.gz')

    def test_catalog_without_applicable_update_cannot_download(self):
        installed,p=self.catalog();p['requires']['revision']='missing'
        with patch.object(a.u,'Manager') as manager:
            manager.return_value.state.return_value={'current':'base'}
            manager.return_value.verify_revision.return_value=installed
            with patch.object(a,'fetch',side_effect=self.signed()),patch.object(a,'open_url') as opening:
                with self.assertRaisesRegex(a.u.UpdateError,'No compatible update'):self.delivery.download()
            opening.assert_not_called()

    def test_catalog_os_base_hashes_select_the_matching_boot_variant(self):
        installed,p=self.catalog();base=self.root/'SYSTEM';base.write_bytes(b'base')
        info={'size':4,'sha256':a.u.sha(base)}
        p.update(kind='os',requires={'runtime':installed['runtime'],'boot_files':{'SYSTEM':info}})
        with patch.object(a,'module') as module:
            module.return_value.OSManager.return_value.boot_file.return_value=base
            meta,_=self.check_catalog(installed);self.assertEqual(meta['package']['id'],'fixture')
            p['requires']['boot_files']['SYSTEM']=dict(info,sha256='0'*64);self.meta['sequence']+=1
            meta,url=self.check_catalog(installed);self.assertIsNone(url)

    def test_github_asset_redirects_preserve_range_and_refuse_other_hosts(self):
        handler=a.NoRedirect()
        request=urllib.request.Request('https://github.com/owner/repo/releases/latest/download/a.tar.gz',headers={'Range':'bytes=0-99'})
        redirected=handler.redirect_request(request,None,302,'',{},'https://github.com/owner/repo/releases/download/v1/a.tar.gz')
        final=handler.redirect_request(redirected,None,302,'',{},'https://release-assets.githubusercontent.com/asset?token=signed')
        self.assertEqual(final.get_header('Range'),'bytes=0-99')
        for url in ['http://release-assets.githubusercontent.com/asset','https://evil.example/a',
                    'https://github.com/other/repo/releases/download/v1/a',
                    'https://user:password@release-assets.githubusercontent.com/asset']:
            with self.assertRaises(a.u.UpdateError):handler.redirect_request(request,None,302,'',{},url)
        lan=urllib.request.Request('http://127.0.0.1/release.json')
        with self.assertRaises(a.u.UpdateError):handler.redirect_request(lan,None,302,'',{},'http://127.0.0.1/other')

    def test_signer_derives_base_specific_catalog_rules(self):
        inside={'schema':2,'id':'fixture','kind':'slot','base':'base','base_sha256':'0'*64,
                'runtime':{'api':1},'target_sha256':'a'*64,'modules':{'selected':['emulator-mgba']}}
        package=self.root/'fixture.tar.gz'
        raw=json.dumps(inside).encode()
        with tarfile.open(package,'w:gz') as archive:
            member=tarfile.TarInfo('manifest.json');member.size=len(raw);archive.addfile(member,io.BytesIO(raw))
        subprocess.run(['python3',str(ROOT/'scripts/sign-rg353v-release.py'),'--catalog',str(package),
                        '--key',str(self.private),'--sequence','1'],check=True,capture_output=True)
        catalog=a.u.load(self.root/'release.json')
        self.assertEqual(catalog['schema'],2)
        self.assertEqual(catalog['packages'][0]['requires'],{'runtime':{'api':1},'revision':'base',
                         'inventory_sha256':'0'*64,'modules':['emulator-mgba']})
        a.verify_signature((self.root/'release.json').read_bytes(),(self.root/'release.json.sig').read_bytes(),[self.public])

    def test_valid_signature_and_exact_repeat(self):
        self.check()
        self.check()
        self.assertEqual(a.u.load(self.delivery.root / 'accepted.json')['sequence'], 1)

    def test_tamper_and_unknown_key(self):
        raw, signature = self.signed()
        with self.assertRaisesRegex(a.u.UpdateError, 'not trusted'):
            a.verify_signature(raw + b' ', signature, [self.public])
        with self.assertRaisesRegex(a.u.UpdateError, 'not trusted'):
            a.verify_signature(raw, signature, [])

    def test_replay_or_conflicting_sequence_rejected(self):
        self.meta['sequence'] = 2
        self.check()
        for sequence in (1, 2):
            self.meta.update(sequence=sequence, notes='conflicting')
            with self.assertRaisesRegex(a.u.UpdateError, 'Older/conflicting'):
                self.check()

    def test_target_and_expiration(self):
        self.meta['target']['device'] = 'x55'
        with self.assertRaisesRegex(a.u.UpdateError, 'target'):
            self.check()
        self.meta['target']['device'] = 'rg353v'
        self.meta['expires'] = 0
        with self.assertRaisesRegex(a.u.UpdateError, 'expired'):
            self.check()

    def test_url_confinement(self):
        for url, dev in [('http://example.com/release.json', True), ('http://10.0.0.1/release.json', False),
                         ('https://user:password@example.com/release.json', False), ('file:///tmp/release.json', True)]:
            with self.assertRaises(a.u.UpdateError):
                a.checked_url(url, dev)
        self.meta['package']['file'] = '../other.tar.gz'
        with self.assertRaises(a.u.UpdateError):
            self.check()

    def test_download_and_cached_download(self):
        with patch.object(a, 'fetch', side_effect=self.signed()), patch.object(a, 'open_url', return_value=io.BytesIO(self.payload)):
            _, target = self.delivery.download()
        self.assertEqual(target.read_bytes(), self.payload)
        with patch.object(a, 'fetch', side_effect=self.signed()), patch.object(a, 'open_url') as opening:
            self.delivery.download()
        opening.assert_not_called()

    def test_only_selected_release_and_its_partial_are_cached(self):
        selected = 'a' * 64
        for name in (selected+'.tar.gz', selected+'.tar.partial', 'b'*64+'.tar.gz',
                     'b'*64+'.tar.partial', 'release.json', 'notes.txt'):
            (self.delivery.root/name).write_text('fixture')
        self.delivery.prune_downloads(selected)
        self.assertEqual({p.name for p in self.delivery.root.iterdir()},
                         {selected+'.tar.gz', selected+'.tar.partial', 'release.json', 'notes.txt'})

    def test_download_retention_never_follows_a_symlink(self):
        outside = self.root/'keep'; outside.write_text('keep')
        (self.delivery.root/('b'*64+'.tar.gz')).symlink_to(outside)
        with self.assertRaisesRegex(a.u.UpdateError, 'Invalid cached update'):
            self.delivery.prune_downloads('a'*64)
        self.assertEqual(outside.read_text(), 'keep')

    def test_corrupt_and_interrupted_download_cleanup(self):
        for payload in (self.payload[:-1], self.payload + b'excess', b'x' * len(self.payload)):
            with patch.object(a, 'fetch', side_effect=self.signed()), patch.object(a, 'open_url', side_effect=lambda *args, **kwargs: io.BytesIO(payload)):
                with self.assertRaises(a.u.UpdateError):
                    self.delivery.download()
            for item in self.delivery.root.glob('*.partial'):
                item.unlink()
            self.assertFalse(list(self.delivery.root.glob('*.tar.gz')))

    def test_resumes_existing_partial_with_exact_range(self):
        partial = self.delivery.root / (self.meta['package']['sha256'] + '.tar.partial')
        partial.write_bytes(self.payload[:40])
        response = io.BytesIO(self.payload[40:])
        response.status = 206
        response.headers = {'Content-Range': f'bytes 40-{len(self.payload)-1}/{len(self.payload)}'}
        with patch.object(a, 'fetch', side_effect=self.signed()), patch.object(a, 'open_url', return_value=response) as opening:
            _, target = self.delivery.download()
        opening.assert_called_once_with('http://127.0.0.1/fixture.tar.gz', {'Range': f'bytes=40-{len(self.payload)-1}'})
        self.assertEqual(target.read_bytes(), self.payload)
        self.assertFalse(partial.exists())

    def test_refuses_wrong_range(self):
        response = io.BytesIO(self.payload)
        response.status = 206
        response.headers = {'Content-Range': 'bytes 1-2/3'}
        with patch.object(a, 'fetch', side_effect=self.signed()), patch.object(a, 'open_url', return_value=response):
            with self.assertRaisesRegex(a.u.UpdateError, 'range response'):
                self.delivery.download()
        self.assertFalse(list(self.delivery.root.glob('*.tar.gz')))

    def test_signed_package_identity_mismatch(self):
        self.meta['package']['id'] = 'other'
        with patch.object(a, 'fetch', side_effect=self.signed()), patch.object(a, 'open_url', return_value=io.BytesIO(self.payload)):
            with self.assertRaisesRegex(a.u.UpdateError, 'identity mismatch'):
                self.delivery.download()

    def test_expected_release_is_checked_before_downloading(self):
        with patch.object(self.delivery, 'check', return_value=(self.meta, 'http://127.0.0.1/x')):
            with self.assertRaisesRegex(a.u.UpdateError, 'changed'):
                self.delivery.download('different-release')
        self.assertFalse(list(self.delivery.root.glob('*.tar.gz')))

    def test_request_runs_outside_slot_and_preserves_expected_version(self):
        with patch.object(a, 'job_active', return_value=False), patch.object(a.subprocess, 'run') as run:
            a.request_job(self.delivery, 'apply', 'fixture')
        args = run.call_args.args[0]
        self.assertEqual(args[0], 'systemd-run')
        self.assertIn('--unit=slot-ota-job', args)
        self.assertIn('systemd-inhibit', args)
        self.assertIn('-B', args)
        self.assertEqual(args[-4:], ['_work', 'apply', '--expected', 'fixture'])
        self.assertEqual(a.u.load(self.delivery.root / 'job.json')['state'], 'starting')
        with patch.object(a, 'job_active', return_value=True):
            with self.assertRaisesRegex(a.u.UpdateError, 'running'):
                a.request_job(self.delivery, 'apply', 'fixture')

    def test_companion_imports_never_add_files_to_a_verified_revision(self):
        system=self.root/'System';system.mkdir()
        source=ROOT/'ports/rg353v/rocknix/slot-rg353v/scripts'
        for name in ('slot-update','slot-os-update','slot-ota'):
            shutil.copy2(source/name,system/('slot-ota-ui' if name=='slot-ota' else name))
        before=a.u.files(system)
        # Deliberately omit -B: the managers must also protect direct launches.
        for name in ('slot-ota-ui','slot-os-update'):
            command='import runpy; runpy.run_path('+repr(str(system/name))+', run_name="qualification")'
            subprocess.run([sys.executable,'-c',command],check=True,capture_output=True)
        self.assertEqual(a.u.files(system),before)
        self.assertFalse((system/'__pycache__').exists())

    def test_worker_error_is_visible_and_releases_lock(self):
        with patch.object(self.delivery, 'check', side_effect=OSError('test disconnect')):
            with self.assertRaisesRegex(OSError, 'disconnect'):
                a.work_job(self.delivery, 'check', '')
        self.assertEqual(a.u.load(self.delivery.root / 'job.json')['state'], 'failed')
        self.assertEqual(a.u.load(self.delivery.root / 'status.json')['event'], 'failed')
        with self.delivery.locked():
            pass

    def test_ui_read_does_not_wait_for_download_lock(self):
        with patch.object(self.delivery, 'locked', side_effect=AssertionError('must not lock')), \
             patch.object(a, 'CONFIG', self.config), patch.object(a, 'Delivery', return_value=self.delivery), \
             patch.object(a.u, 'runtime'), patch.object(a, 'ui_snapshot') as snapshot, \
             patch.object(a.sys, 'argv', ['slot-ota', 'ui']):
            a.main()
        snapshot.assert_called_once_with(self.delivery)

    def test_ui_reads_progress_while_worker_holds_delivery_lock(self):
        with self.delivery.locked(), patch.object(a.u, 'Manager') as manager, \
             patch.object(a, 'module') as module, patch.object(a, 'job_active', return_value=True):
            manager.return_value.state.return_value = {'current': 'fixture', 'previous': None}
            module.return_value.OSManager.return_value.active.return_value = None
            self.delivery.event('downloading', bytes=64, size=100)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                a.ui_snapshot(self.delivery)
            self.assertIn('bytes\t64', output.getvalue())
            self.assertIn('busy\t1', output.getvalue())

    def test_successful_reboot_is_not_reported_as_interrupted_job(self):
        a.u.atomic_json(self.delivery.root / 'job.json', {'state': 'running', 'operation': 'apply'})
        with patch.object(a.u, 'Manager') as manager, patch.object(a, 'module') as module, \
             patch.object(a, 'job_active', return_value=False), \
             patch.object(self.delivery, 'status', return_value={'event': 'installed'}):
            manager.return_value.state.return_value = {'current': 'fixture', 'previous': None}
            module.return_value.OSManager.return_value.active.return_value = {'id': 'os1', 'phase': 'confirmed'}
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                a.ui_snapshot(self.delivery)
            self.assertIn('event\tinstalled', output.getvalue())
            self.assertNotIn('interrupted', output.getvalue())

    def test_rollback_stale_selection_cannot_stop_slot(self):
        with patch.object(a, 'shelf_and_power'), patch.object(a.u, 'Manager') as manager, \
             patch.object(a.subprocess, 'run') as run:
            manager.return_value.state.return_value = {'current': 'newer'}
            with self.assertRaisesRegex(a.u.UpdateError, 'changed'):
                a.rollback('rollback-slot', 'older')
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
