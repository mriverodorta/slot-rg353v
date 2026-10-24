#!/usr/bin/env python3
"""Export a private setup profile from an explicitly named development device.

The resulting file contains Wi-Fi credentials: keep it private. Public builds
never call this exporter or include its output. It includes no private SSH keys,
password hashes, machine IDs, saves or settings from the handheld.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--host',required=True);p.add_argument('--identity',type=Path,required=True)
p.add_argument('--known-hosts',type=Path,required=True);p.add_argument('--public-key',type=Path,required=True)
p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():p.error('Output already exists')
if a.public_key.suffix!='.pub':p.error('Supply a public .pub key, never a private key')
code="""from pathlib import Path
import base64,json
paths=sorted(Path('/storage/.config/NetworkManager/system-connections').glob('*.nmconnection'))
print(json.dumps([{'name':'wifi-'+str(i)+'.nmconnection','data':base64.b64encode(v.read_bytes()).decode()} for i,v in enumerate(paths) if v.is_file() and not v.is_symlink()]))
"""
r=subprocess.run(['ssh','-i',str(a.identity),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                  '-o','UserKnownHostsFile='+str(a.known_hosts),'-o','ConnectTimeout=5',a.host,'python3 -'],
                 input=code,text=True,capture_output=True,check=True,timeout=30)
obj={'schema':1,'wifi':json.loads(r.stdout),'authorized_keys':[a.public_key.read_text().strip()]}
a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
fd=os.open(a.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
with os.fdopen(fd,'w') as f:json.dump(obj,f);f.flush();os.fsync(f.fileno())
s=importlib.util.spec_from_file_location('debug',ROOT/'ports/rg353v/image/slot-setup-debug.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
try:m.load(a.output)
except Exception:a.output.unlink();raise
print('Private developer profile saved; contents omitted.')
