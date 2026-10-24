#!/usr/bin/env python3
"""Privacy checks redact matches, do not follow image links and fail on seeded data."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

p=Path(__file__).with_name('audit-rg353v-release.py')
spec=importlib.util.spec_from_file_location('audit',p);a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class Audit(unittest.TestCase):
    def test_seeded_profiles_keys_and_personal_content_fail(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            for path in ('boot/slot-setup-debug.json','storage/.ssh/authorized_keys','etc/ssh/ssh_host_ed25519_key.pub','Games/GBA/example.gba','etc/NetworkManager/system-connections/example.nmconnection'):
                f=root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('fixture')
            r=a.inspect(root,'tree')
            self.assertFalse(r['passed']);self.assertEqual(len(r['findings']),5)
    def test_actual_private_material_is_detected_but_code_literals_are_not(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);prefix='-----BEGIN '+'PRIVATE KEY-----'
            (root/'code.py').write_text(repr(prefix+'\n'+('A'*100)))
            self.assertTrue(a.inspect(root,'tree')['passed'])
            (root/'leak.txt').write_text(prefix+'\n'+('A'*100)+'\n')
            r=a.inspect(root,'tree');self.assertEqual(r['findings'],[{'path':'leak.txt','reason':'private_key_material'}])
    def test_matches_are_redacted_and_chunk_boundaries_are_checked(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);value=b'private-password-fixture'
            (root/'leak.bin').write_bytes(b'0'*(1024*1024-8)+value)
            r=a.inspect(root,'tree',[('owner_wifi_value',value)])
            self.assertFalse(r['passed']);self.assertNotIn(value.decode(),json.dumps(r))
    def test_absolute_image_links_are_recorded_without_reading_host_files(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'host').symlink_to('/etc/passwd')
            r=a.inspect(root,'tree');self.assertTrue(r['passed'])
            self.assertEqual(r['files'],[{'path':'host','type':'symlink','target':'/etc/passwd'}])
    def test_private_profile_decodes_wifi_without_returning_password_in_report(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'profile.json'
            wifi=b'[connection]\nid=Example\n[wifi]\nssid=PrivateTest\n[wifi-security]\npsk=private-fixture-password\n'
            p.write_text(json.dumps({'schema':1,'wifi':[{'name':'example.nmconnection','data':base64.b64encode(wifi).decode()}],'authorized_keys':['ssh-ed25519 publicfixture comment']}))
            tokens=a.profile_tokens(p)
            self.assertIn(('owner_wifi_value',b'private-fixture-password'),tokens)
            self.assertIn(('owner_public_key',b'publicfixture'),tokens)
    def test_archive_coverage_limits_are_explicit(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'module.tar.gz').write_bytes(b'fixture')
            self.assertEqual(a.inspect(root,'tree')['compressed_files_not_opened'],['module.tar.gz'])
if __name__=='__main__':unittest.main()
