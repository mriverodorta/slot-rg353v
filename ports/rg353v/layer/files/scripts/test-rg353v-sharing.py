#!/usr/bin/env python3
"""File sharing settings, isolation, status and rollback regressions."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('sharing', str(ROOT/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-sharing'))
spec = importlib.util.spec_from_loader(loader.name, loader)
sharing = importlib.util.module_from_spec(spec)
loader.exec_module(sharing)

class SharingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.services = {'slot-sharing.service': True}
        self.fail = False
        self.ip = '192.0.2.10'
        self.controller = sharing.Controller(self.root, self.run_command, lambda: self.ip)
        self.controller.config.parent.mkdir(parents=True)
        self.controller.config.write_text('wifi.enabled=1\nssh.enabled=1\nsamba.enabled=1\ncustom=x\n')
        self.controller.share.write_text('[global]\nmap to guest = Bad User\n[Slot]\npath=/storage/slotcontent\nguest ok=yes\nread only=no\n[Private]\npath=/storage/private\nvalid users=someone\n')
        self.original_share = self.controller.share.read_bytes()

    def run_command(self, args):
        self.calls.append(args)
        rc = 0
        if args[0] == '/bin/bash':
            value = args[-2]
            lines = [s for s in self.controller.config.read_text().splitlines() if not s.startswith('samba.enabled=')]
            if value != 'default': lines.append('samba.enabled='+value)
            self.controller.config.write_text('\n'.join(lines)+'\n')
        elif args[:2] == ['systemctl','is-active']:
            rc = 0 if self.services[args[2]] else 3
        elif args[0] == 'systemctl':
            if self.fail:
                self.fail = False
                # Simulate a partial failure: one service did change.
                self.services[args[2]] = args[1] == 'start'
                rc = 1
            else:
                for service in args[2:]: self.services[service] = args[1] == 'start'
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args,rc,stdout='',stderr='')

    def test_toggle_persists_and_only_changes_samba(self):
        for enabled in [False,True]:
            result = self.controller.set(enabled)
            self.assertEqual(result['enabled'], str(int(enabled)))
            self.assertEqual(result['state'], 'Running' if enabled else 'Off')
            self.assertEqual(self.controller.disabled.exists(), not enabled)
            self.assertEqual(self.controller.setting(), '1' if enabled else '0')
            self.assertEqual(self.controller.share.read_bytes(), self.original_share)
            self.assertIn('wifi.enabled=1\nssh.enabled=1\ncustom=x', self.controller.config.read_text())
        for call in self.calls:
            if call[0] == 'systemctl': self.assertTrue(all(s in self.services for s in call[2:]))
        self.assertEqual(sharing.Controller(self.root,self.run_command,lambda: self.ip).status()['enabled'],'1')

    def test_rollback_after_partial_failure(self):
        self.fail = True
        with self.assertRaisesRegex(sharing.SharingError, 'previous setting restored'):
            self.controller.set(False)
        self.assertEqual(self.controller.setting(),'1')
        self.assertFalse(self.controller.disabled.exists())
        self.assertEqual(self.services, {'slot-sharing.service': True})

    def test_rollback_restores_absent_key_and_disabled_services(self):
        self.controller.config.write_text('wifi.enabled=1\nssh.enabled=1\n')
        self.services = {'slot-sharing.service':False}
        self.controller.marker(True)
        self.fail = True
        with self.assertRaises(sharing.SharingError): self.controller.set(True)
        self.assertIsNone(self.controller.setting())
        self.assertTrue(self.controller.disabled.exists())
        self.assertFalse(any(self.services.values()))

    def test_status_tracks_address_and_reports_real_service_state(self):
        self.assertEqual(self.controller.status()['address'],'smb://192.0.2.10/Slot')
        self.ip = '192.168.2.2'
        self.assertEqual(self.controller.status()['address'],'smb://192.168.2.2/Slot')
        self.ip = ''
        self.assertEqual(self.controller.status()['state'],'Waiting for network')
        self.services['slot-sharing.service'] = False
        self.assertEqual(self.controller.status()['state'],'Service stopped')
        self.controller.share.write_text('[global]\n')
        self.assertEqual(self.controller.status()['state'],'Share unavailable')

    def test_preserves_authenticated_share_and_reports_access(self):
        self.controller.share.write_text('[global]\nmap to guest=Never\n[Slot]\nguest ok=no\nvalid users=customuser\n')
        original = self.controller.share.read_bytes()
        self.assertEqual(self.controller.status()['access'],'Login required')
        self.controller.set(False)
        self.controller.set(True)
        self.assertEqual(self.controller.share.read_bytes(),original)

if __name__ == '__main__': unittest.main(verbosity=2)
