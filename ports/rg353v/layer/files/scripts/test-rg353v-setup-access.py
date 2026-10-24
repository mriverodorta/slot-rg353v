#!/usr/bin/env python3
"""Private setup network configuration and public-image exclusion checks."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('access','ports/rg353v/image/slot-setup-access.py')
c=load('composer','scripts/compose-rg353v-clean.py')

def profile(key='wpa-psk'):
 value='[connection]\nid=fixture\n[wifi]\nssid=IEEE\n[wifi-security]\nkey-mgmt='+key+'\npsk=password\n[ipv4]\nmethod=auto\n'
 return {'wifi':[{'name':'fixture.nmconnection','data':base64.b64encode(value.encode()).decode()}],'authorized_keys':['fixture public key']}
class Access(unittest.TestCase):
 def test_wpa_config_encodes_ssid_and_psk_without_plain_password(self):
  text=m.wpa_config(profile())
  self.assertIn('ssid=49454545',text);self.assertNotIn('password',text)
  self.assertIn('psk=f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e',text)
  self.assertNotIn('update_config=1',text)
 def test_unsupported_enterprise_or_static_profiles_stop_without_exposing_secrets(self):
  for key in ('wpa-eap','sae','none'):
   with self.assertRaisesRegex(ValueError,'No supported saved Wi-Fi profile'):m.wpa_config(profile(key))
 def test_concurrent_status_publication_preserves_both_transports(self):
  with tempfile.TemporaryDirectory() as temp:
   x=m.Access({},Path(temp)/'unused','unused',runtime=Path(temp))
   workers=[threading.Thread(target=x.status,kwargs={name:value}) for name,value in [('wifi','10.0.0.2'),('usb','172.31.53.1'),('ssh',True)]]
   for worker in workers:worker.start()
   for worker in workers:worker.join()
   self.assertEqual(json.loads((Path(temp)/'status.json').read_text()),{'wifi':'10.0.0.2','usb':'172.31.53.1','ssh':True})
 def test_firmware_lookup_uses_the_kernel_init_root_before_switch_root(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   with self.assertRaisesRegex(ValueError,'firmware source'):m.firmware_path(root)
   normal=root/'usr/lib/kernel-overlays/base/lib/firmware';normal.mkdir(parents=True)
   self.assertEqual(m.firmware_path(root),'/usr/lib/kernel-overlays/base/lib/firmware')
   early=root/'sysroot/usr/lib/kernel-overlays/base/lib/firmware';early.mkdir(parents=True)
   self.assertEqual(m.firmware_path(root),'/sysroot/usr/lib/kernel-overlays/base/lib/firmware')
 def test_wifi_status_binds_its_client_socket_in_ram(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);x=m.Access({},root/'unused','unused',runtime=root);x.wifi='wlan0'
   with patch.object(m,'command') as execute:
    self.assertEqual(x.wifi_status(),'');execute.assert_not_called()
    (root/'wpa').mkdir();(root/'wpa/wlan0').touch()
    execute.return_value=SimpleNamespace(stdout='wpa_state=COMPLETED\n')
    self.assertIn('COMPLETED',x.wifi_status())
    execute.assert_called_once_with(['/usr/bin/slot-wpa-cli','-p',str(root/'wpa'),'-s',str(root),'-i','wlan0','status'])
 def test_public_composition_refuses_any_private_input_before_loading(self):
  for kwargs in ({'debug_profile':Path('private')},{'host_key':Path('host')},{'setup_debug':True}):
   with self.assertRaisesRegex(ValueError,'Public images cannot contain private provisioning'):
    c.compose(Path('input.img'),Path('output.img'),Path('loader'),public=True,**kwargs)
  with tempfile.TemporaryDirectory() as temp:
   kit=Path(temp);(kit/'private').mkdir()
   with self.assertRaisesRegex(ValueError,'Private module data is not distributable'):
    c.compose(Path('input.img'),Path('output.img'),Path('loader'),module_kit=kit,public=True)
if __name__=='__main__':unittest.main()
