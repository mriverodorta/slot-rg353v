#!/usr/bin/env python3
"""Read-only private provisioning snapshot for an offline test-card image."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

REMOTE = r'''
from pathlib import Path
import os,sys,tarfile
root=Path('/storage')
assert 'cart=' in (root/'slotcontent/Config/slot.state').read_text().splitlines(),'Eject the game first'
folders=['Games','BIOS','Labels','Wallpapers','Saves','States','Config']
private=['.config/system/configs/system.cfg','.config/NetworkManager','.cache/NetworkManager','.cache/ssh','.cache/slot-ssh','.cache/shadow','.cache/services','.ssh/authorized_keys','.config/slot-boot-profiler.enabled','.configured']
items=[]
for prefix,base,names in [('content',root/'slotcontent',folders),('storage',root,private)]:
 for name in names:
  source=base/name
  if source.is_symlink():raise RuntimeError('Unsupported provisioning symlink')
  for p in sorted(source.rglob('*')) if source.is_dir() else [source]:
   if p.is_symlink():raise RuntimeError('Unsupported provisioning symlink')
   if p.is_file():items.append((prefix+'/'+str(p.relative_to(base)),p))
assert len(items)<20000
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
 for name,p in items:
  with p.open('rb') as file:
   st=os.fstat(file.fileno());assert st.st_size<=256*1024**2
   info=tarfile.TarInfo(name);info.size=st.st_size;info.mode=0o600;info.mtime=int(st.st_mtime)
   archive.addfile(info,file)
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',required=True,help='Handheld IP address')
    p.add_argument('--key',type=Path,default=Path.home()/'.ssh/slot_rg353v_ed25519')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=900,help='Maximum SSH snapshot transfer seconds (300–1800)')
    a=p.parse_args();ipaddress.ip_address(a.host)
    if not 300<=a.timeout<=1800:raise ValueError('Timeout must be 300–1800 seconds')
    if a.output.exists():raise ValueError('Output exists; refusing to merge snapshots')
    a.output.mkdir(parents=True,mode=0o700)
    ssh=['ssh','-i',str(a.key),'-o','BatchMode=yes','-o','ConnectTimeout=5','root@'+a.host,'python3 -']
    inventory={}
    with tempfile.TemporaryFile() as temp:
        subprocess.run(ssh,input=REMOTE.encode(),stdout=temp,check=True,timeout=a.timeout)
        temp.seek(0)
        with tarfile.open(fileobj=temp,mode='r:') as archive:
            total=0
            for item in archive:
                name=PurePosixPath(item.name)
                if not item.isfile() or name.is_absolute() or '..' in name.parts or name.parts[0] not in ('storage','content'):
                    raise ValueError('Unsupported snapshot entry')
                if item.name in inventory or item.size>256*1024**2:raise ValueError('Invalid snapshot inventory')
                total+=item.size
                if total>2*1024**3:raise ValueError('Snapshot exceeds 2 GiB bound')
                dst=a.output.joinpath(*name.parts);dst.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                sha=hashlib.sha256()
                with archive.extractfile(item) as source,dst.open('xb') as out:
                    for block in iter(lambda:source.read(1024**2),b''):out.write(block);sha.update(block)
                dst.chmod(0o600)
                inventory[item.name]={'bytes':item.size,'sha256':sha.hexdigest()}
    for name in ('storage','content'):(a.output/name).mkdir(exist_ok=True,mode=0o700)
    manifest={'schema':1,'private':True,'files':inventory}
    path=a.output/'snapshot.json';path.write_text(json.dumps(manifest,indent=2)+'\n');path.chmod(0o600)
    print(json.dumps({'output':str(a.output),'files':len(inventory),'bytes':sum(x['bytes'] for x in inventory.values()),'private':True}))

if __name__=='__main__':main()
