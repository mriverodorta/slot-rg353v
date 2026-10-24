#!/usr/bin/env python3
"""Fixed recovery input: live filesystem discovery, ioctl outcomes and fallback."""
import os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'ports/rg353v/rocknix/slot-bootsplash'
@unittest.skipUnless(sys.platform=='linux','evdev headers require Linux')
class NativeKey(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.bin=self.root/'probe'
  self.model=self.root/'sys/firmware/devicetree/base/compatible';self.model.parent.mkdir(parents=True)
  self.model.write_bytes(b'anbernic,rg353v\0rockchip,rk3566\0')
  self.event=self.root/'sys/devices/platform/gpio-keys-vol/input/input3/event3';self.event.mkdir(parents=True)
  self.node=self.root/'dev/input/event3';self.node.parent.mkdir(parents=True);self.node.touch()
  subprocess.run([os.environ.get('CC','cc'),'-O2','-Wall','-Wextra','-Werror','-std=c11','-DSLOT_RECOVERY_ROOT="'+str(self.root)+'"','-Dioctl=slot_test_ioctl','-Dfstat=slot_test_fstat',str(PKG/'src/slot-recovery-key.c'),str(PKG/'tests/recovery-key-ioctl.c'),'-o',str(self.bin)],check=True)
 def run_probe(self,scenario='released',*args):
  return subprocess.run([str(self.bin),*args],env=dict(os.environ,SLOT_TEST_KEY=scenario),capture_output=True,timeout=2).returncode
 def test_held_released_and_up_are_distinct(self):
  for state,code in [('held',0),('both',0),('released',1),('up',1)]:
   with self.subTest(state=state):self.assertEqual(self.run_probe(state),code)
 def test_failed_or_untrusted_device_queries_request_fallback(self):
  for state in ('not-char','wrong-name','name-error','caps-error','missing-key','read-error'):
   with self.subTest(state=state):self.assertEqual(self.run_probe(state),2)
 def test_model_is_required_and_nul_delimited(self):
  for model in (b'other\0',b'anbernic,rg353v-extra\0',b'anbernic,rg353v',b'x'*512):
   with self.subTest(model=model[:30]):
    self.model.write_bytes(model);self.assertEqual(self.run_probe(),2)
  self.model.unlink();self.assertEqual(self.run_probe(),2)
 def test_missing_node_and_missing_or_ambiguous_discovery_request_fallback(self):
  self.node.unlink();self.assertEqual(self.run_probe(),2);self.node.touch()
  self.event.rmdir();self.assertEqual(self.run_probe(),2);self.event.mkdir()
  (self.event.parent/'event4').mkdir();self.assertEqual(self.run_probe(),2)
 def test_unknown_arguments_are_not_accepted(self):self.assertEqual(self.run_probe('released','--ignore-errors'),2)
class ShellFallback(unittest.TestCase):
 def test_unknown_result_and_missing_helper_keep_original_scan(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('bootpatch',PKG/'tools/patch-boot.py')
  patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);helper=root/'helper';called=root/'called';fallback=root/'fallback'
   hook=patch.RECOVERY_KEY_HOOK.replace('/usr/bin/slot-recovery-key',str(helper))
   body='is_key_pressed() {\n'+hook+'  echo fallback >"'+str(fallback)+'"\n  return 7\n}\n'
   query='if is_key_pressed "$KEY"; then exit 0; else exit "$?"; fi\n'
   for code,wanted,scan in [(0,0,False),(1,1,False),(2,7,True),(127,7,True)]:
    helper.write_text('#!/bin/sh\necho called >"'+str(called)+'"\nexit '+str(code)+'\n');helper.chmod(0o755)
    called.unlink(missing_ok=True);fallback.unlink(missing_ok=True)
    result=subprocess.run(['sh','-ec',body+query],env=dict(os.environ,KEY='114'),capture_output=True)
    self.assertEqual(result.returncode,wanted);self.assertEqual(fallback.exists(),scan);self.assertTrue(called.exists())
   helper.unlink();fallback.unlink(missing_ok=True)
   self.assertEqual(subprocess.run(['sh','-ec',body+query],env=dict(os.environ,KEY='114'),capture_output=True).returncode,7)
   self.assertTrue(fallback.exists())
 def test_other_keys_and_forced_recovery_skip_native_probe(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('bootpatch',PKG/'tools/patch-boot.py')
  patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);helper=root/'helper';called=root/'called'
   helper.write_text('#!/bin/sh\necho called >"'+str(called)+'"\nexit 1\n');helper.chmod(0o755)
   hook=patch.RECOVERY_KEY_HOOK.replace('/usr/bin/slot-recovery-key',str(helper))
   body='is_key_pressed() {\n'+hook+'  return 1\n}\n'
   subprocess.run(['sh','-ec',body+'if is_key_pressed 115; then :; fi'],check=True)
   self.assertFalse(called.exists())
   query='FORCE_RECOVERY=yes; if [ "$FORCE_RECOVERY" != yes ] && ! is_key_pressed 114; then exit 9; fi'
   subprocess.run(['sh','-ec',body+query],check=True);self.assertFalse(called.exists())
if __name__=='__main__':unittest.main()
