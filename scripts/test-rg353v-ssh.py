#!/usr/bin/env python3
"""SSH isolation, hashed credentials and explicit key import regressions."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('slotssh',str(ROOT/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-ssh'))
spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
HASH=b'$6$testsalt$'+b'A'*86

class SSHTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.calls=[];self.active=True;self.fail=False
        self.c=module.Controller(self.root,self.execute)
        self.c.settings.parent.mkdir(parents=True)
        self.c.settings.write_text('wifi.enabled=1\nsamba.enabled=1\nssh.enabled=1\n')
        self.c.marker.parent.mkdir(parents=True);self.c.marker.write_bytes(b'SSH_ARGS="-p 22"\n')
        self.c.shadow.write_text('root:oldhash:123::::::\nother:!*:123::::::\n')
        self.c.install_boot_guard=lambda: (self.c.private.mkdir(parents=True,exist_ok=True), self.c.private.chmod(0o700))
    def execute(self,args,data=None):
        self.calls.append((args,data));rc=0;out=b''
        if args[0]=='/bin/bash':
            v=args[-2];lines=[l for l in self.c.settings.read_text().splitlines() if not l.startswith('ssh.enabled=')]
            if v!='default':lines.append('ssh.enabled='+v)
            self.c.settings.write_text('\n'.join(lines)+'\n')
        elif args[:2]==['systemctl','is-active']:rc=0 if self.active else 3
        elif args[0]=='systemctl':
            self.active=args[1]=='start'
            if self.fail:self.fail=False;rc=1
        elif args[:2]==['openssl','passwd']:out=HASH+b'\n'
        elif args[0]=='ssh-keygen':return subprocess.run(args,input=data,capture_output=True,timeout=10)
        else:raise AssertionError(args)
        return subprocess.CompletedProcess(args,rc,out,b'')
    def test_toggle_preserves_other_services_settings_and_ssh_args(self):
        original=self.c.marker.read_bytes()
        self.c.set(False);self.assertFalse(self.active);self.assertFalse(self.c.marker.exists())
        self.c.set(True);self.assertTrue(self.active);self.assertEqual(self.c.marker.read_bytes(),original)
        self.assertIn('wifi.enabled=1\nsamba.enabled=1',self.c.settings.read_text())
        for args,_ in self.calls:
            if args[0]=='systemctl':self.assertEqual(args[-1],'sshd.service')
    def test_service_failure_rolls_back(self):
        self.fail=True
        with self.assertRaises(module.SSHError):self.c.set(False)
        self.assertTrue(self.active);self.assertEqual(self.c.setting(),'1');self.assertTrue(self.c.marker.exists())
    def test_password_is_hashed_stdin_only_and_preserves_other_accounts(self):
        secret=b'Only for a fixture!'
        self.c.password(secret)
        self.assertEqual(self.c.hashfile.read_bytes(),HASH+b'\n')
        self.assertEqual(self.c.shadow.stat().st_mode&0o777,0)
        self.c.shadow.chmod(0o600)
        self.assertIn('other:!*:123::::::',self.c.shadow.read_text())
        self.assertNotIn(secret,self.c.settings.read_bytes());self.assertNotIn(secret,self.c.hashfile.read_bytes())
        for args,data in self.calls:
            self.assertNotIn(secret.decode(),args)
            if args[0]=='openssl':self.assertEqual(data,secret+b'\n')
        self.assertEqual(self.c.hashfile.stat().st_mode&0o777,0o600)
    def test_reject_invalid_password_and_hash_without_shadow_changes(self):
        original=self.c.shadow.read_bytes()
        for secret in [b'',b'short',b'A'*65,b'long\npassword',b'long\x00password']:
            with self.assertRaises(module.SSHError):self.c.password(secret)
        self.assertEqual(original,self.c.shadow.read_bytes())
        self.c.private.mkdir();self.c.hashfile.write_text('not-a-hash')
        with self.assertRaises(module.SSHError):self.c.restore_password()
        self.assertEqual(original,self.c.shadow.read_bytes())
    def key(self,name):
        self.c.inbox.mkdir(parents=True,exist_ok=True)
        path=self.c.inbox/name
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(path)],check=True)
        return Path(str(path)+'.pub')
    def test_key_import_is_explicit_idempotent_and_preserves_existing_keys(self):
        p=self.key('mac');self.c.keys.parent.mkdir();existing='# Existing managed key\nssh-ed25519 AAAA existing\n';self.c.keys.write_text(existing)
        preview=self.c.preview();self.assertEqual(preview['count'],'1');self.assertEqual(self.c.keys.read_text(),existing)
        self.c.import_keys(preview['digest']);saved=self.c.keys.read_text();self.assertTrue(saved.startswith(existing))
        self.c.import_keys(preview['digest']);self.assertEqual(saved,self.c.keys.read_text())
        self.assertEqual(self.c.keys.stat().st_mode&0o777,0o600)
        self.assertEqual(self.c.keys.parent.stat().st_mode&0o777,0o700)
        self.assertIn(' '.join(p.read_text().split()[:2]),saved)
    def test_reject_changed_private_or_symlink_key(self):
        p=self.key('mac');digest=self.c.preview()['digest'];p.write_text('PRIVATE KEY DATA')
        with self.assertRaises(module.SSHError):self.c.import_keys(digest)
        p.unlink();p.symlink_to('/etc/passwd')
        with self.assertRaises(module.SSHError):self.c.preview()

if __name__=='__main__':unittest.main(verbosity=2)
