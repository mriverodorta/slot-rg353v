#!/usr/bin/env python3
"""Private setup opt-in, filesystem boundaries and credential isolation tests."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('debug',ROOT/'ports/rg353v/image/slot-setup-debug.py')
ui=load('debug_ui',ROOT/'ports/rg353v/image/slot-setup-ui.py')
KEY='ssh-ed25519 '+base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+bytes(32)).decode()+' fixture'
def profile():return {'schema':1,'wifi':[{'name':'wifi-0.nmconnection','data':base64.b64encode(b'[connection]\nid=fixture\ntype=wifi\n[wifi]\nssid=fixture\n[wifi-security]\npsk=fixture-secret\n').decode()}],'authorized_keys':[KEY]}
class Debug(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.path=self.root/'profile.json';self.path.write_text(json.dumps(profile()))
  self.state=self.root/'state';self.state.mkdir();(self.state/'.slot-clean-layout.json').write_text('{"phase":"complete"}')
 def test_normal_image_has_no_profile_or_extra_setup_page(self):
  self.assertIsNone(m.load(self.root/'absent')); model=ui.Model({'bytes':10,'content_bytes':1},None)
  model.key('a');self.assertEqual(model.page,'confirm');self.assertFalse(any(model.options.values()))
 def test_private_profile_checkbox_dependencies_and_confirmation(self):
  model=ui.Model({'bytes':10,'content_bytes':1},None,m.load(self.path));model.key('a')
  self.assertEqual(model.page,'debug');self.assertTrue(all(model.options.values()))
  model.key('a');model.key('down');model.key('a');self.assertFalse(model.options['ssh'])
  model.key('down');model.key('a');model.key('down');model.key('a')
  self.assertEqual(model.page,'confirm');self.assertIsNone(model.key('a'));self.assertEqual(model.page,'choose')
 def test_only_selected_destination_gets_profiles_and_public_key(self):
  other=self.root/'other';other.mkdir();(other/'save').write_text('untouched')
  m.provision(self.state,m.load(self.path),dict(wifi=True,usb=True,ssh=True))
  self.assertEqual((other/'save').read_text(),'untouched')
  key=self.state/'.ssh/authorized_keys';self.assertEqual(key.read_text(),KEY+'\n');self.assertEqual(key.stat().st_mode&0o777,0o600)
  self.assertEqual(key.parent.stat().st_mode&0o777,0o700)
  self.assertIn('PasswordAuthentication=no',(self.state/'.cache/slot-ssh/sshd.env').read_text())
  self.assertFalse((self.state/'.config/slot/features-v1').exists(),'debug policy must not hide installed features')
  self.assertEqual((self.state/'.config/slot/developer-usb').read_text(),'1\n')
  for name in ('machine-id','shadow','ssh_host_ed25519_key'):
   self.assertFalse(list(self.state.rglob(name)))
 def test_usb_only_does_not_copy_wifi_credentials(self):
  m.provision(self.state,m.load(self.path),dict(wifi=False,usb=True,ssh=True))
  self.assertFalse((self.state/'.config/NetworkManager').exists())
 def test_profile_and_destination_guards(self):
  for change in ({'authorized_keys':['PRIVATE KEY']},{'wifi':[{'name':'../escape.nmconnection','data':'AA=='}]},{'schema':2}):
   obj=profile();obj.update(change);self.path.write_text(json.dumps(obj))
   with self.assertRaises((ValueError,TypeError)):m.load(self.path)
  (self.state/'.slot-clean-layout.json').write_text('{"phase":"copying"}')
  with self.assertRaises(ValueError):m.provision(self.state,profile(),dict(wifi=True,ssh=True))
 def test_ssh_requires_a_transport(self):
  with self.assertRaises(ValueError):m.provision(self.state,profile(),dict(wifi=False,usb=False,ssh=True))
 def test_debug_view_renders_and_contains_no_secrets(self):
  model=ui.Model({'bytes':10,'content_bytes':1},None,profile());model.page='debug'
  canvas=ui.Canvas(ROOT/'ports/rg353v/image/slot-setup-font.json.gz');model.draw(canvas)
  self.assertEqual(len(canvas.pixels),640*480*4)
if __name__=='__main__':unittest.main()
