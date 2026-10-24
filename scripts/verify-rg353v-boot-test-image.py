#!/usr/bin/env python3
"""Verify a private test image offline; never accepts a host block device."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

spec=importlib.util.spec_from_file_location('layout',Path(__file__).with_name('rg353v-card-layout.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as file:
  for block in iter(lambda:file.read(8*1024**2),b''):h.update(block)
 return h.hexdigest()

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--firmware-report',type=Path,required=True);a=p.parse_args()
assert a.image.is_file() and not a.image.is_block_device()
parts=m.partitions(a.image);assert set(parts)=={1,2,3}
snapshot=json.loads((a.snapshot/'snapshot.json').read_text())
firmware=json.loads(a.firmware_report.read_text());payload=next(x['payload'] for x in firmware['artifacts'].values() if 'payload' in x)
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)
 for i in range(1,4):
  mount=root/str(i);mount.mkdir()
  with m.mounted(a.image,*parts[i],mount):
   device=m.run('findmnt','-n','-o','SOURCE',mount,capture=True).strip()
   if i==1:
    for name in ('KERNEL','SYSTEM'):assert sha(mount/name)==payload[name]['sha256']
   else:
    prefix='storage/' if i==2 else 'content/'
    for name,data in snapshot['files'].items():
     if name.startswith(prefix):
      path=mount/name[len(prefix):]
      assert path.is_file() and path.stat().st_size==data['bytes'] and sha(path)==data['sha256'],name
    if i==2:
     key=mount/'.ssh/authorized_keys'
     assert key.is_file() and key.stat().st_uid==0 and key.stat().st_mode&0o777==0o600
     assert not (mount/'.please_resize_me').exists()
    else:assert m.run('findmnt','-n','-o','FSTYPE',mount,capture=True).strip()=='exfat'
   # The filesystem is mounted read-only. Checkers open its loop device read-only too.
   checker={1:['fsck.fat','-n'],2:['e2fsck','-f','-n'],3:['fsck.exfat','-n']}[i]
   m.run(*checker,device)
report={'schema':1,'image':a.image.name,'bytes':a.image.stat().st_size,'partitions':parts,'private_provisioning':True,'snapshot_files_verified':len(snapshot['files']),'content_files_verified':sum(n.startswith('content/') for n in snapshot['files']),'kernel_system_match_firmware':True,'filesystem_checks_passed':True,'ssh_key_owner_mode_verified':True}
a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
