#!/usr/bin/env python3
"""Split a validated root into a core and disjoint optional file packages.

Run on Linux: kernel module paths can differ only in letter case. Libraries
shared with the core stay there; optional-only libraries follow their consumers.
"""
import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('modules',ROOT/'ports/rg353v/image/slot-modules.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def build(root,owners_file,tools,output):
    root,tools,output=map(Path,(root,tools,output))
    if output.exists():raise ValueError('Module output already exists')
    output.mkdir(mode=0o700,parents=True)
    spec=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text());modules=spec['modules'];owner_paths=json.loads(Path(owners_file).read_text())
    inventory={str(p.relative_to(root)):m.info(p) for p in sorted(root.rglob('*'))}
    assigned={n:set() for n,v in inventory.items() if v['type']!='directory'}
    for module in modules:
        for name in assigned:
            if name in owner_paths.get(module['id'], []) or any(fnmatch.fnmatchcase(name,pattern) for pattern in module['paths']):assigned[name].add(module['id'])
    # Every module's unit drop-ins and activation links belong with that unit.
    for name in list(assigned):
        if not name.startswith('usr/lib/systemd/system/'):continue
        tail=name.removeprefix('usr/lib/systemd/system/');unit=tail.split('/',1)[0]
        if '.d/' in tail:unit=unit.removesuffix('.d')
        entry=inventory[name]
        if entry['type']=='symlink' and entry['target']!='/dev/null':
            target=entry['target'].split('/')[-1];unit=target
        assigned[name].update(assigned.get('usr/lib/systemd/system/'+unit,set()))
    # Scan actual ELF requirements; no library is removed on name alone.
    elf={}
    for name,entry in inventory.items():
        if entry['type']!='file':continue
        p=root/name
        with p.open('rb') as f:magic=f.read(4)
        if magic!=b'\x7fELF':continue
        data=subprocess.check_output(['readelf','-d',str(p)],text=True,stderr=subprocess.DEVNULL)
        elf[name]=re.findall(r'\(NEEDED\).*\[(.*?)\]',data)
    by_name={}
    for name in assigned:by_name.setdefault(Path(name).name,[]).append(name)
    def lib(name):
        candidates=by_name.get(name,[])
        candidates=[n for n in candidates if n.startswith(('usr/lib/','lib/'))]
        if len(candidates)>1:
            candidates=sorted(candidates,key=lambda n:(len(Path(n).parts),n))
        return candidates[0] if candidates else None
    def symlink_chain(name):
        seen=set()
        while inventory[name]['type']=='symlink':
            if name in seen:raise ValueError('Library symlink cycle')
            seen.add(name);target=inventory[name]['target']
            name=os.path.normpath(target.lstrip('/') if target.startswith('/') else str(Path(name).parent/target))
            if name not in inventory:raise ValueError('Missing library symlink target: '+name)
        return seen|{name}
    def closure(seeds):
        found=set();pending=list(seeds)
        while pending:
            n=pending.pop()
            for path in symlink_chain(n):
                if path in found:continue
                found.add(path)
                for needed in elf.get(path,[]):
                    dependency=lib(needed)
                    if dependency is None:raise ValueError(f'Missing ELF dependency {needed} for {path}')
                    pending.append(dependency)
        return found
    module_reach={m0['id']:closure(n for n in elf if m0['id'] in assigned[n]) for m0 in modules}
    candidates=set().union(*module_reach.values())
    def library(name):return name.startswith('usr/lib/') and re.search(r'\.so(?:\.|$)',Path(name).name) is not None and '/python' not in name and '/dri/' not in name
    core_roots=[n for n in elf if not assigned[n] and (not library(n) or n not in candidates)]
    core_reach=closure(core_roots)
    for n in candidates:
        if n in core_reach:
            assigned[n]=set()
        elif library(n) or inventory[n]['type']=='symlink':
            assigned[n]={owner for owner,paths in module_reach.items() if n in paths}
    # All symlink aliases of a split library must share its ownership.
    for n in assigned:
        if inventory[n]['type']=='symlink' and inventory[n]['target']!='/dev/null' and library(n):
            chain=symlink_chain(n)
            targets=[v for v in chain if inventory[v]['type']=='file']
            if targets:assigned[n]=assigned[targets[0]].copy()
    buckets={}
    for n,owners in assigned.items():buckets.setdefault(tuple(sorted(owners)),[]).append(n)
    core=output/'core';core.mkdir()
    for n,entry in inventory.items():
        if entry['type']=='directory':(core/n).mkdir(parents=True,exist_ok=True);(core/n).chmod(entry['mode'])
    for name in buckets.pop((),[]):
        src=root/name;dest=core/name
        if inventory[name]['type']=='symlink':dest.symlink_to(inventory[name]['target'])
        else:shutil.copy2(src,dest)
    catalog={'schema':1,'kind':'slot-module-kit','device':'rg353v','id':spec['id'],'modules':[{k:v for k,v in x.items() if k not in ('packages','paths')} for x in modules], 'core_inventory':{n:m.info(core/n) for n in inventory if (core/n).exists() or (core/n).is_symlink()},'packages':[],'payloads':[], 'optional_units':sorted(Path(n).name for n,v in assigned.items() if v and n.startswith('usr/lib/systemd/system/') and len(Path(n).parts)==5 and n.endswith(('.service','.socket','.timer','.path')))}
    subprocess.run(['mksquashfs',str(core),str(output/'core.sfs'),'-comp','lz4','-Xhc','-b','65536','-noappend','-all-root','-no-xattrs','-no-progress','-processors','2','-mem','64M'],check=True,stdout=subprocess.DEVNULL)
    shutil.rmtree(core)
    for group,names in sorted(buckets.items()):
        label=hashlib.sha256(','.join(group).encode()).hexdigest()[:16];filename='packages/'+label+'.tar.gz';p=output/filename;p.parent.mkdir(exist_ok=True)
        with tarfile.open(p,'w:gz') as tar:
            for name in sorted(names):
                src=root/name;entry=inventory[name];meta=tarfile.TarInfo(name);meta.uid=meta.gid=0;meta.mode=entry['mode'];meta.mtime=0
                if entry['type']=='symlink':meta.type=tarfile.SYMTYPE;meta.linkname=entry['target'];tar.addfile(meta)
                else:
                    meta.size=entry['bytes']
                    with src.open('rb') as f:tar.addfile(meta,f)
        catalog['packages'].append({'owners':list(group),'file':filename,'inventory':{n:inventory[n] for n in names}})
    (output/'tools').mkdir()
    for name in ['mksquashfs','unsquashfs']:
        shutil.copy2(tools/name,output/'tools'/name);(output/'tools'/name).chmod(0o755)
    for p in sorted(output.rglob('*')):
        if p.is_file():catalog['payloads'].append({'file':str(p.relative_to(output)),'bytes':p.stat().st_size,'sha256':m.digest(p)})
    m.save(output/'catalog.json',catalog)
    m.save(output/'ownership.json',{'files':{n:sorted(v) for n,v in assigned.items()},'source_files':len(assigned),'core_files':sum(not owners for owners in assigned.values()),'optional_files':sum(bool(owners) for owners in assigned.values())})
    print(json.dumps({'core_bytes':(output/'core.sfs').stat().st_size,'packages':len(catalog['packages']),'optional_files':sum(bool(v) for v in assigned.values()),'kit_bytes':sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--owners',type=Path,required=True);p.add_argument('--tools',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.root,a.owners,a.tools,a.output)
