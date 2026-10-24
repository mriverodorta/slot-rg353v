#!/usr/bin/env python3
"""Explicit, private installer provisioning. Never copies host identities or passwords.

A developer profile is optional and absent from public images. It contains only
NetworkManager Wi-Fi keyfiles and authorized PUBLIC keys. The installer copies
it to RAM before expansion and writes only the selected destination's storage.
"""
import base64
import json
import os
from pathlib import Path
import re
import tempfile

PROFILE='slot-setup-debug.json'

def load(path):
    path=Path(path)
    if not path.exists():return None
    if path.stat().st_size>128*1024 or path.is_symlink():raise ValueError('Invalid developer profile')
    obj=json.loads(path.read_text())
    if set(obj)!={'schema','wifi','authorized_keys'} or obj['schema']!=1:raise ValueError('Unsupported developer profile')
    if not isinstance(obj['wifi'],list) or len(obj['wifi'])>8:raise ValueError('Invalid Wi-Fi profile list')
    for entry in obj['wifi']:
        if (not isinstance(entry,dict) or set(entry)!={'name','data'}
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\.nmconnection',entry['name'])):
            raise ValueError('Invalid Wi-Fi profile name')
        data=base64.b64decode(entry['data'],validate=True)
        if len(data)>16384 or b'[wifi]' not in data or b'[connection]' not in data or b'\x00' in data:
            raise ValueError('Invalid Wi-Fi profile data')
    if len({v['name'] for v in obj['wifi']})!=len(obj['wifi']):raise ValueError('Duplicate Wi-Fi profile')
    if not isinstance(obj['authorized_keys'],list) or len(obj['authorized_keys'])>8:raise ValueError('Invalid public key list')
    for key in obj['authorized_keys']:
        fields=key.split()
        if len(fields)<2 or fields[0]!='ssh-ed25519' or '\n' in key or '\r' in key or len(key)>1024:
            raise ValueError('Only public Ed25519 keys are accepted')
        blob=base64.b64decode(fields[1],validate=True)
        if len(blob)!=51 or blob[:19]!=b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':raise ValueError('Invalid public SSH key')
    return obj

def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():raise ValueError('Unsafe provisioning destination')
    fd,name=tempfile.mkstemp(prefix='.setup-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(name):os.unlink(name)

def provision(storage,profile,options):
    storage=Path(storage)
    if not any(options.values()):return
    if profile is None:raise ValueError('Developer profile is unavailable')
    marker=storage/'.slot-clean-layout.json'
    if marker.is_symlink() or json.loads(marker.read_text()).get('phase')!='complete':
        raise ValueError('Developer access requires a completed installation')
    if options.get('ssh') and not (options.get('wifi') or options.get('usb')):
        raise ValueError('SSH requires Wi-Fi or USB networking')
    if options.get('wifi') and not profile['wifi']:raise ValueError('No saved Wi-Fi profiles')
    if options.get('ssh') and not profile['authorized_keys']:raise ValueError('No public SSH key')
    if options.get('wifi'):
        for item in profile['wifi']:
            atomic(storage/'.config/NetworkManager/system-connections'/item['name'],base64.b64decode(item['data'],validate=True))
    if options.get('ssh'):
        keys=storage/'.ssh';keys.mkdir(mode=0o700,exist_ok=True);keys.chmod(0o700)
        atomic(keys/'authorized_keys',('\n'.join(profile['authorized_keys'])+'\n').encode())
        atomic(storage/'.cache/slot-ssh/sshd.env',b'SSH_ARGS="-o PasswordAuthentication=no -o KbdInteractiveAuthentication=no"\n')
    # Restrict developer startup to the transports chosen on setup. General
    # services not requested here remain opt-in; no host private key is copied.
    selected=['developer','usb-storage','external-sd','filters','overlays','frame-counter','rewind','runahead','updates','diagnostics','profilers']
    selected += [name for option,name in [('wifi','wifi'),('usb','usb-network'),('ssh','ssh')] if options.get(option)]
    # This is a developer-startup policy, not the installed feature inventory.
    atomic(storage/'.config/slot/setup-developer-features-v1',('slot-features-v1\n'+'\n'.join(selected)+'\n').encode())
    atomic(storage/'.config/slot/developer-usb',b'1\n' if options.get('usb') else b'0\n')
    atomic(storage/'.config/slot/developer-mode',b'1\n')
