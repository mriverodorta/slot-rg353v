#!/usr/bin/env python3
"""Exercise acknowledged hardware timing and bounded external-command fallback."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'ports/rg353v/rocknix/slot-startup-profile/scripts/slot-hardware-start'


class Marks(unittest.TestCase):
    def test_timestamps_reuse_one_process_and_failures_never_block_hardware_setup(self):
        for mode in ('normal','exit','stall','exit-after-ack'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
                root=Path(t);capture=root/'calls';helper=root/'splash'
                helper.write_text('''#!/usr/bin/env python3
import os,sys,json,time
from pathlib import Path
capture=Path(os.environ['MARK_CAPTURE'])
def record(kind,value):
 with capture.open('a') as f:f.write(json.dumps([kind,os.getpid(),value])+'\\n')
if sys.argv[1]=='--stream':
 mode=os.environ['MARK_MODE']
 if mode=='exit':sys.exit(2)
 if mode=='stall':time.sleep(10)
 for line in sys.stdin:
  record('stream',line.strip());print('ok',flush=True)
  if mode=='exit-after-ack':sys.exit(0)
else:record('external',' '.join(sys.argv[1:]))
''');helper.chmod(0o755)
                text=SOURCE.read_text();text=text[text.index('marks_pid='):text.index('# Parse once;')]
                text=text.replace('/usr/bin/slot-splash',str(helper))
                script='set -e\nlog='+str(root/'boot.log')+'\n'+text+'''
start_marks || :
for n in 1 2 3 4; do
 step "test-$n" true
 ignored=$(printf value)
done
finish_marks
'''
                env=dict(os.environ,MARK_CAPTURE=str(capture),MARK_MODE=mode)
                p=subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True,timeout=4)
                self.assertEqual(p.returncode,0,p.stderr)
                calls=[json.loads(line) for line in capture.read_text().splitlines()]
                self.assertEqual(len(calls),8)
                expected=[f'{kind} hardware-test-{n}' for n in range(1,5) for kind in ('--begin','--event')]
                self.assertEqual([line[2] for line in calls],expected)
                if mode=='normal':
                    self.assertEqual({line[0] for line in calls},{'stream'})
                    self.assertEqual(len({line[1] for line in calls}),1)
                else:self.assertIn('external',{line[0] for line in calls})


if __name__=='__main__':unittest.main()
