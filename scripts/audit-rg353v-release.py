#!/usr/bin/env python3
"""Read-only privacy inventory of publishable source or an extracted image tree.

Does not unpack images/archives, inspect Git history, or grant license approval.
Supply every extracted filesystem/module tree for a complete image review.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

KEY = re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{32,}')
PRIVATE_DIRS = {'localdev', '.private-rg353v'}
SOURCE_EXCLUDED = PRIVATE_DIRS | {'resources', 'release'}
ARCHIVES = ('.gz', '.xz', '.zip', '.zst', '.sfs', '.squashfs', '.img')

def profile_tokens(path):
    if path is None:
        return []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128*1024:
        raise ValueError('Use the bounded private setup profile, not a key file')
    profile = json.loads(path.read_text())
    if profile.get('schema') != 1:
        raise ValueError('Unsupported private profile')
    tokens = []
    for key in profile.get('authorized_keys', []):
        fields = key.split()
        if len(fields) >= 2:
            tokens.append(('owner_public_key', fields[1].encode()))
    for entry in profile.get('wifi', []):
        data = base64.b64decode(entry['data'], validate=True)
        tokens.extend([('owner_wifi_profile', data), ('owner_encoded_wifi_profile', entry['data'].encode())])
        for match in re.finditer(rb'(?m)^\s*(psk|password|ssid)\s*=\s*(.+?)\s*$', data):
            value = match[2].strip()
            if len(value) >= 4:
                tokens.append(('owner_wifi_value', value))
    return [(kind, value) for kind, value in tokens if value]

def scan(path, tokens):
    found = set()
    overlap = max([4096] + [len(value) for _, value in tokens])
    digest = hashlib.sha256()
    tail = b''
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
            chunk = tail + block
            if KEY.search(chunk): found.add('private_key_material')
            for kind, value in tokens:
                if value in chunk: found.add(kind)
            tail = chunk[-overlap:]
    return digest.hexdigest(), sorted(found)

def selected(root, mode):
    if mode == 'source':
        names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root)
        return sorted(set(os.fsdecode(v) for v in names.split(b'\0') if v))
    names = []
    def unreadable(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
        # Include symlinked directories as entries without following them.
        names.extend((Path(directory)/name).relative_to(root).as_posix() for name in files)
        names.extend((Path(directory)/name).relative_to(root).as_posix() for name in dirs if (Path(directory)/name).is_symlink())
    return sorted(names)

def inspect(root, mode, tokens=()):
    root = root.resolve(strict=True)
    if not root.is_dir(): raise ValueError('Use a source directory or extracted filesystem tree')
    files, findings, archives = [], [], []
    for name in selected(root, mode):
        path = root/name
        try: info = path.lstat()
        except FileNotFoundError: continue  # Locally deleted tracked file.
        parts = set(Path(name).parts)
        forbidden = SOURCE_EXCLUDED if mode == 'source' else PRIVATE_DIRS
        reasons = set()
        if parts & forbidden: reasons.add('private_or_generated_directory')
        if path.is_symlink():
            if mode == 'source': reasons.add('source_symlink_requires_review')
            files.append({'path':name,'type':'symlink','target':os.readlink(path)})
        elif not stat.S_ISREG(info.st_mode):
            reasons.add('unsupported_file_type')
        else:
            if root not in path.resolve().parents:
                reasons.add('path_escapes_root')
            else:
                digest, detected = scan(path, tokens)
                reasons.update(detected)
                files.append({'path':name,'type':'file','bytes':info.st_size,'sha256':digest})
                if name.endswith(ARCHIVES): archives.append(name)
            if mode == 'tree':
                if path.name in ('slot-setup-debug.json','authorized_keys','authorized_keys2') or path.name.startswith('ssh_host_'):
                    reasons.add('seeded_development_identity_or_profile')
                if path.name.endswith('.nmconnection') or (path.suffix in ('.psk','.8021x') and 'iwd' in parts):
                    reasons.add('seeded_wifi_connection')
                if any(p in parts for p in ('Games','Saves','States','BIOS','Screenshots')) and info.st_size:
                    reasons.add('personal_content_requires_review')
        for reason in sorted(reasons): findings.append({'path':name,'reason':reason})
    return {'schema':1,'mode':mode,'passed':not findings,'files':files,'file_count':len(files),
            'regular_bytes':sum(v.get('bytes',0) for v in files),'findings':findings,
            'compressed_files_not_opened':archives,
            'scope':'Selected source files or this extracted tree only. Archives, Git history, other filesystems/modules, licenses and physical qualification require separate review.'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['source','tree'])
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--private-profile',type=Path,help='Optional owner setup profile; matched values are never included in output')
    a=p.parse_args()
    root=a.root.resolve(strict=True);output=a.output.resolve()
    if output==root or root in output.parents:
        p.error('Keep audit reports outside the audited tree')
    result=inspect(root,a.mode,profile_tokens(a.private_profile))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('passed','file_count','regular_bytes')},sort_keys=True))
    raise SystemExit(0 if result['passed'] else 1)
if __name__=='__main__':main()
