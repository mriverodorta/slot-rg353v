#!/usr/bin/env python3
"""Remove reviewed inactive graphics/development payloads from the complete image."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def resolve(root, path):
    parts=list(path.relative_to(root).parts);current=[];links=0
    while parts:
        part=parts.pop(0)
        if part in ('','/','.'):continue
        if part=='..':
            if not current:raise ValueError('Image link escapes root')
            current.pop();continue
        p=root.joinpath(*current,part)
        if p.is_symlink():
            links+=1
            if links>40:raise ValueError('Image link loop')
            link=p.readlink()
            if link.is_absolute():current=[]
            parts=list(link.parts)+parts
        else:current.append(part)
    return root.joinpath(*current)


def check_dependencies(root, excluded):
    aliases=set();needed={};elf_paths=set()
    for p in root.rglob('*'):
        if p.is_symlink() or not p.is_file() or str(p.relative_to(root)) in excluded:continue
        with p.open('rb') as f:header=f.read(20)
        if len(header)<20 or header[:4]!=b'\x7fELF':continue
        order={1:'<',2:'>'}.get(header[5])
        if not order:raise ValueError('Invalid ELF encoding')
        if struct.unpack_from(order+'H',header,16)[0] not in (2,3):continue
        text=subprocess.run(['readelf','--wide','--dynamic',str(p)],capture_output=True,text=True,check=True).stdout
        aliases.add(p.name);aliases.update(re.findall(r'\(SONAME\).*?\[(.*?)\]',text))
        elf_paths.add(str(p.relative_to(root)))
        needed[str(p.relative_to(root))]=re.findall(r'\(NEEDED\).*?\[(.*?)\]',text)
    for p in root.rglob('*'):
        if not p.is_symlink() or str(p.relative_to(root)) in excluded:continue
        target=resolve(root,p)
        if str(target.relative_to(root)) in elf_paths:aliases.add(p.name)
    missing={n:[v for v in names if v not in aliases] for n,names in needed.items()}
    missing={n:v for n,v in missing.items() if v}
    if missing:raise ValueError('Trim leaves unresolved ELF dependencies: '+json.dumps(missing,sort_keys=True))


def prune(root, policy_path, dependency_check=check_dependencies, report_name='image-prune.json'):
    if report_name not in ('image-prune.json', 'appliance-prune.json'):
        raise ValueError('Invalid trim report path')
    root=root.resolve();factory=json.loads((root/'usr/share/slot/os-profile.json').read_text())
    if factory.get('userspace_profile','baseline')=='baseline' or factory.get('build_profile')=='development':
        return {'removed':[],'profile':'untrimmed'}
    hardware=json.loads((root/'usr/share/slot/hardware/profile.json').read_text())
    if (factory.get('device')!='rg353v' or factory.get('userspace_profile')!='rg353v-lean-v1'
            or factory.get('build_profile')!='normal' or hardware.get('model')!='anbernic,rg353v'
            or hardware.get('panel')!='anbernic,rg353v-panel-v2' or hardware.get('gpu')!='mali_kbase'):
        raise ValueError('Unqualified image profile')
    policy=json.loads(policy_path.read_text())
    if policy['schema']!=1 or policy['profile']!='rg353v-lean-v1':raise ValueError('Unsupported image policy')
    protected={x['path']:x['sha256'] for x in hardware['fixed_libraries']}
    protected_names={f'usr/lib/{name}' for name in ('libEGL.so','libEGL.so.1','libGLESv1_CM.so','libGLESv1_CM.so.1','libGLESv2.so','libGLESv2.so.2','libgbm.so','libgbm.so.1','libmali.so.1')}
    for name,wanted in protected.items():
        p=root/name
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=wanted:
            raise ValueError('Changed fixed graphics library: '+name)
    removed=[]
    for name,entry in policy['remove'].items():
        relative=Path(name)
        # The sole etc exception is the reviewed, unused EmulationStation
        # controller profile. Never permit general configuration-tree pruning.
        allowed = name.startswith(('usr/lib/','usr/bin/','usr/sbin/','usr/share/')) or name == 'etc/profile.d/100-gamecontroller-functions'
        if (relative.is_absolute() or '..' in relative.parts or not allowed
                or '/licenses/' in name or name.startswith('usr/share/slot/System/')
                or name in protected or name in protected_names):
            raise ValueError('Protected/invalid image trim path: '+name)
        p=root/relative
        if any(parent.is_symlink() for parent in p.parents if parent!=root and root in parent.parents):
            raise ValueError('Image trim crosses parent symlink: '+name)
        if p.is_symlink():
            if entry.get('link')!=str(p.readlink()):raise ValueError('Changed image link: '+name)
            removed.append({'path':name,'link':entry['link'],'group':entry['group'],'bytes':0})
        elif p.exists():
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=entry.get('sha256'):
                raise ValueError('Review changed image payload: '+name)
            removed.append({'path':name,'sha256':entry['sha256'],'group':entry['group'],'bytes':p.stat().st_size})
    # No unlink occurs until the full path/hash plan and retained ELF graph pass.
    dependency_check(root,set(policy['remove']))
    for entry in removed:(root/entry['path']).unlink()
    report={'profile':'rg353v-lean-v1','removed':removed,'removed_bytes':sum(x['bytes'] for x in removed),'fixed_libraries_sha256':protected,'remaining_elf_dependencies':'passed'}
    output=root/'usr/share/slot/hardware'/report_name
    if removed or not output.exists():output.write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--policy',type=Path,default=Path(__file__).parents[1]/'config/image-prune.json')
    args=parser.parse_args();result=prune(args.root,args.policy)
    print(json.dumps({k:v for k,v in result.items() if k!='removed'},indent=2))
