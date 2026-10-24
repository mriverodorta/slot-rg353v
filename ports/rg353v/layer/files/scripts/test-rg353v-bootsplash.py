#!/usr/bin/env python3
"""Real renderer, milestone accounting and boot hook regression tests."""
import sys
sys.dont_write_bytecode=True
import importlib.machinery,importlib.util,json,os,re,subprocess,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'ports/rg353v/rocknix/slot-bootsplash'
def module(name,path):
 loader=importlib.machinery.SourceFileLoader(name,str(path));spec=importlib.util.spec_from_loader(name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m);return m
m=module('progress',PKG/'scripts/slot-boot-progress');patcher=module('patch_boot',PKG/'tools/patch-boot.py')
PLAN=json.loads((PKG/'config/boot-plan.json').read_text())
IDS=['init-'+s for s in PLAN['init']]+['service-'+s['id'] for s in PLAN['services']]+['frontend-'+s for s in PLAN['frontend']]
class SplashTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.bin=cls.root/'splash';cls.state=cls.root/'state'
  subprocess.run([os.environ.get('CC','cc'),'-O2','-std=c11','-Wall','-Wextra','-Werror','-DROOT="'+str(cls.state)+'"',str(PKG/'src/slot-splash.c'),'-lm','-o',str(cls.bin)],check=True)
  cls.init_bin=cls.root/'splash-init'
  subprocess.run([os.environ.get('CC','cc'),'-O2','-std=c11','-Wall','-Wextra','-Werror','-DSLOT_SPLASH_INIT',str(PKG/'src/slot-splash.c'),'-lm','-o',str(cls.init_bin)],check=True)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def test_count_matches_shared_plan(self):
  self.assertEqual(re.findall(r'"([a-z_-]+)"',(PKG/'src/plan.h').read_text()),IDS)
  self.assertEqual(len(set(IDS)),29)
 def test_real_events_gate_one_hundred_and_reject_paths(self):
  self.assertEqual(subprocess.check_output([self.bin,'--percent'],text=True).strip(),'0')
  for name in IDS[:-1]:subprocess.run([self.bin,'--event',name],check=True)
  self.assertEqual(subprocess.check_output([self.bin,'--percent'],text=True).strip(),'96')
  self.assertEqual(subprocess.run([self.bin,'--event','../outside'],capture_output=True).returncode,2)
  subprocess.run([self.bin,'--event',IDS[-1]],check=True)
  self.assertEqual(subprocess.check_output([self.bin,'--percent'],text=True).strip(),'100')
 def test_precise_spans_are_exclusive_and_do_not_advance_progress(self):
  subprocess.run([self.bin,'--begin','hardware-test-span'],check=True)
  first=(self.state/'begins/hardware-test-span').read_text()
  self.assertGreater(float(first),0)
  subprocess.run([self.bin,'--begin','hardware-test-span'],check=True)
  self.assertEqual(first,(self.state/'begins/hardware-test-span').read_text())
  subprocess.run([self.bin,'--event','hardware-test-span'],check=True)
  self.assertGreaterEqual(float((self.state/'events/hardware-test-span').read_text()),float(first))
  for name in ('../escape','hardware-../escape','hardware-','arbitrary','hardware-foo/bar'):
   self.assertEqual(subprocess.run([self.bin,'--begin',name],capture_output=True).returncode,2)
 def test_stream_acknowledges_persisted_precise_marks_and_exits_on_eof(self):
  p=subprocess.Popen([self.bin,'--stream'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  try:
   for kind in ('--begin','--event'):
    p.stdin.write(kind+' hardware-stream-test\n');p.stdin.flush()
    self.assertEqual(p.stdout.readline(),'ok\n')
    folder='begins' if kind=='--begin' else 'events'
    self.assertGreater(float((self.state/folder/'hardware-stream-test').read_text()),0)
   self.assertGreaterEqual(float((self.state/'events/hardware-stream-test').read_text()),float((self.state/'begins/hardware-stream-test').read_text()))
   p.stdin.close();self.assertEqual(p.wait(timeout=2),0)
  finally:
   if p.poll() is None:p.kill();p.wait()
   p.stdout.close()
 def test_stream_rejects_invalid_framing_commands_and_paths(self):
  for data in ('--event ../escape\n','--delete hardware-valid\n','--event hardware-valid extra\n','--event hardware-truncated','x'*250+'\n','--event hardware-nul\0extra\n'):
   p=subprocess.run([self.bin,'--stream'],input=data,text=True,capture_output=True,timeout=2)
   self.assertEqual(p.returncode,2,data);self.assertEqual(p.stdout,'')
 def test_render_frames_are_full_panel_and_fill_is_truthful(self):
  frames={}
  for percent in (0,40,100):
   path=self.root/(str(percent)+'.rgba');subprocess.run([self.bin,'--rgba',str(percent),path],check=True);data=path.read_bytes();self.assertEqual(len(data),640*480*4);frames[percent]=data
  def at(p,x,y):return frames[p][(y*640+x)*4:(y*640+x)*4+3]
  self.assertLess(at(0,220,278)[1],100)
  self.assertGreater(at(40,220,278)[1],150)
  self.assertLess(at(40,420,278)[1],100)
  self.assertGreater(at(100,420,278)[1],150)
  for value in ('-1','101','3x'):
   self.assertEqual(subprocess.run([self.bin,'--rgba',value,self.root/'bad'],capture_output=True).returncode,2)
 def test_init_renderer_keeps_the_same_static_boot_frames(self):
  for percent in (0,40,100):
   files=[self.root/(str(percent)+'-'+name) for name in ('normal','init')]
   for binary,path in zip((self.bin,self.init_bin),files):subprocess.run([binary,'--rgba',str(percent),path],check=True)
   self.assertEqual(files[0].read_bytes(),files[1].read_bytes())
 def test_boot_completion_does_not_wait_for_optional_network_services(self):
  names={u for item in PLAN['services'] for u in item['units']}
  self.assertTrue(names.isdisjoint({'NetworkManager.service','slot-wpa-supplicant.service','sshd.service','smbd.service'}))
  units={name:{'Id':name,'ActiveState':'active','LoadState':'loaded'} for name in names}
  self.assertEqual(len(m.observe(PLAN,units,{})),len(PLAN['services']))
 def test_skips_and_failures_are_recorded_without_fake_readiness(self):
  self.assertEqual(m.outcome({'LoadState':'masked'},True),'skipped')
  self.assertIsNone(m.outcome({'LoadState':'masked'},False))
  self.assertEqual(m.outcome({'ActiveState':'failed'}),'failed')
  self.assertIsNone(m.outcome({'ActiveState':'activating'}))
  self.assertEqual(m.outcome({'ActiveState':'inactive','ConditionResult':'no','ConditionTimestampMonotonic':'123'}),'skipped')
 def test_boot_hooks_are_idempotent_and_check_upstream_contract(self):
  with tempfile.TemporaryDirectory() as t:
   tree=Path(t);p=tree/'projects/ROCKNIX/packages/sysutils/busybox/scripts/init';p.parent.mkdir(parents=True)
   body='error() {\n  echo error\n}\nload_splash() {\n  /usr/bin/rocknix-splash\n  echo original\n}\nrecovery_mode() {\n  StartProgress spinner "Exporting storage as USB MSC... "\n}\nSILENT_OUT=3\nfor BOOT_STEP in \\\n'+''.join('    '+n+' \\\n' for n in PLAN['init'])+'do\n  ${BOOT_STEP}\n  [ -n "${DEBUG}" ] && true\ndone\n'
   body=body.replace('SILENT_OUT=3\n', 'is_key_pressed() {\n  return 1\n}\nSILENT_OUT=3\n')
   body=body.replace('    '+PLAN['init'][-1]+' '+chr(92)+'\n','    '+PLAN['init'][-1]+'\n')
   body+='# switch to new sysroot and start real init\nexec /usr/bin/busybox switch_root /sysroot /usr/lib/systemd/systemd\n'
   p.write_text(body);meta=tree/'projects/ROCKNIX/packages/virtual/initramfs/package.mk';meta.parent.mkdir(parents=True);meta.write_text('PKG_DEPENDS_INIT="libc:init"\nfor i in ${PKG_DEPENDS_INIT}; do\n :\ndone\n')
   patcher.patch(tree,PLAN);once=p.read_text();patcher.patch(tree,PLAN);self.assertEqual(once,p.read_text());self.assertIn('echo original',once);self.assertIn('slot-bootsplash:init',meta.read_text())
   self.assertLess(once.index('# Slot RG353V early splash'),once.index('for BOOT_STEP'))
   self.assertLess(once.index('# Slot RG353V persisted identity'),once.index('# switch to new sysroot'))
   self.assertIn('"${FORCE_RECOVERY}" != yes',once)
   self.assertIn('"${DEBUG}" != yes',once)
   self.assertIn('[ -z "${INIT_UNIT}" ]',once)
   self.assertIn('--draw || :',once)
   self.assertIn('--error || :\n  StartProgress spinner',once)
   subprocess.run(['sh','-n',str(p)],check=True)
   stub=tree/'splash-stub';stub.write_text('#!/bin/sh\necho called\nexit 1\n');stub.chmod(0o755)
   start=once.index('if [ -z "${INIT_UNIT}" ]')
   early=once[start:once.index('\nfi',start)+3].replace('/usr/bin/slot-splash',str(stub))
   for overrides,expected in [({},'called'),({'INIT_UNIT':'--unit=textmode.target'},''),({'FORCE_RECOVERY':'yes'},''),({'DEBUG':'yes'},'')]:
    env={**os.environ,'INIT_UNIT':'','FORCE_RECOVERY':'no','DEBUG':'',**overrides}
    result=subprocess.run(['sh','-c',early],env=env,text=True,capture_output=True,check=True)
    self.assertEqual(result.stdout.strip(),expected)
   stub.unlink()
   subprocess.run(['sh','-c',early],check=True)
   p.write_text(body.replace('    recovery_mode \\\n',''))
   with self.assertRaisesRegex(RuntimeError,'milestones'):patcher.patch(tree,PLAN)
   for contract,message in [('SILENT_OUT=3','early-init output'),('  StartProgress spinner "Exporting storage as USB MSC... "','recovery display')]:
    p.write_text(body.replace(contract,''))
    with self.assertRaisesRegex(RuntimeError,message):patcher.patch(tree,PLAN)
    self.assertEqual(p.read_text(),body.replace(contract,''))
 def test_identity_marker_requires_a_successful_check_and_clears_stale_marker(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);marker=root/'ready';checker=root/'checker'
   command='/usr/bin/busybox chroot /sysroot /usr/bin/slot-machine-id-setup --check /etc/machine-id /storage/.cache/systemd-machine-id'
   hook=patcher.IDENTITY_HOOK.replace(command,str(checker)).replace('/sysroot/usr/bin/slot-machine-id-setup',str(checker)).replace('/sysroot/run/slot-machine-id-ready',str(marker))
   for code in (0,1):
    checker.write_text('#!/bin/sh\nexit '+str(code)+'\n');checker.chmod(0o755)
    marker.write_text('stale')
    subprocess.run(['sh','-c',hook],check=True)
    self.assertEqual(marker.exists(),code==0)
   checker.unlink();marker.write_text('stale')
   subprocess.run(['sh','-c',hook],check=True);self.assertFalse(marker.exists())
@unittest.skipUnless(sys.platform=='linux','production inotify/poll wait requires Linux')
class HandoffWaitTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.state=self.root/'state';self.bin=self.root/'wait'
  subprocess.run([os.environ.get('CC','cc'),'-O2','-std=c11','-Wall','-Wextra','-Werror','-DROOT="'+str(self.state)+'"',str(PKG/'tests/handoff-wait.c'),'-lm','-o',str(self.bin)],check=True)
 def start(self,*args):
  p=subprocess.Popen([self.bin,*args],stdout=subprocess.PIPE,text=True)
  def cleanup():
   if p.poll() is None:p.kill();p.wait()
   p.stdout.close()
  self.addCleanup(cleanup)
  deadline=time.monotonic()+2
  while not (self.state/'wait.ready').exists():
   self.assertIsNone(p.poll());self.assertLess(time.monotonic(),deadline);time.sleep(.005)
  return p
 def test_handoff_and_error_interrupt_the_five_second_animation_wait(self):
  for marker in ('handoff','failed'):
   with self.subTest(marker=marker):
    p=self.start();(self.state/marker).touch()
    self.assertEqual(p.communicate(timeout=1)[0],'1\n');self.assertEqual(p.returncode,0)
    (self.state/marker).unlink();(self.state/'wait.ready').unlink()
 def test_preexisting_marker_cannot_be_missed(self):
  self.state.mkdir();(self.state/'handoff').touch()
  p=self.start();self.assertEqual(p.communicate(timeout=1)[0],'1\n')
 def test_unrelated_frame_events_do_not_complete_handoff(self):
  p=self.start()
  for n in range(30):
   (self.state/'frame.tmp').write_text(str(n));(self.state/'frame.tmp').replace(self.state/'frame.rgba')
  time.sleep(.05);self.assertIsNone(p.poll())
  (self.state/'handoff').touch();self.assertEqual(p.communicate(timeout=1)[0],'1\n')
 def test_signal_and_missing_watch_fallback_remain_bounded(self):
  p=self.start();p.terminate();self.assertEqual(p.communicate(timeout=1)[0],'1\n')
  (self.state/'wait.ready').unlink()
  started=time.monotonic();p=self.start('fallback')
  self.assertEqual(p.communicate(timeout=1)[0],'0\n');self.assertGreaterEqual(time.monotonic()-started,.08)
if __name__=='__main__':unittest.main()
