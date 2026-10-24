#!/usr/bin/env python3
"""Validated installation-time composition; no module mounting on normal boot."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

EMULATORS={'emulator-mgba':'mgba_libretro.so','emulator-gpsp':'gpsp_libretro.so'}

ID=re.compile(r'[a-z][a-z0-9-]{0,63}\Z')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.slot-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(obj,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(tmp,path);syncdir(path.parent)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def syncdir(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def safe_name(name):
    if not isinstance(name,str) or not name or len(name)>512:raise ValueError('Invalid module path')
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or str(p)!=name or any(c in name for c in ('\x00','\n','\r')):raise ValueError('Invalid module path')
    return p

def load(kit):
    kit=Path(kit);data=json.loads((kit/'catalog.json').read_text())
    if data.get('schema')!=1 or data.get('kind')!='slot-module-kit' or data.get('device')!='rg353v':raise ValueError('Unsupported module kit')
    modules=data.get('modules',[]);ids=[m['id'] for m in modules]
    if len(set(ids))!=len(ids) or not all(ID.fullmatch(i) for i in ids):raise ValueError('Invalid module identifiers')
    for m in modules:
        if not set(m['requires'])<=set(ids):raise ValueError('Unknown module dependency')
        for group in m.get('requires_any',[]):
            if not group or not set(group)<=set(ids):raise ValueError('Unknown alternative module dependency')
        if not set(m.get('available_with',[]))<=set(ids):raise ValueError('Unknown feature prerequisite')
    payloads=data['payloads']
    if len(payloads)>128 or len({x['file'] for x in payloads})!=len(payloads):raise ValueError('Invalid payload list')
    for item in payloads:
        safe_name(item['file'])
        if type(item['bytes']) is not int or not 0<item['bytes']<=512*1024**2 or not re.fullmatch('[0-9a-f]{64}',item['sha256']):raise ValueError('Invalid module payload descriptor')
    known={x['file'] for x in payloads}
    if not {'core.sfs','tools/mksquashfs','tools/unsquashfs'}<=known:raise ValueError('Missing composition tools')
    used=set(data['core_inventory'])
    for package in data['packages']:
        if package['file'] not in known or not set(package['owners'])<=set(ids):raise ValueError('Invalid package owner')
        if used & package['inventory'].keys():raise ValueError('Overlapping module inventories')
        used.update(package['inventory'])
    if len(used)>50000:raise ValueError('Oversize module inventory')
    for name in used:safe_name(name)
    return data

def selection(catalog,chosen):
    chosen=set(chosen);modules={m['id']:m for m in catalog['modules']}
    if not chosen<=modules.keys():raise ValueError('Unknown selected feature')
    before=None
    while before!=chosen:
        before=chosen.copy()
        for name in list(chosen):
            chosen.update(modules[name]['requires'])
            for group in modules[name].get('requires_any',[]):
                if not chosen.intersection(group):chosen.add(group[0])
    if modules.keys() & EMULATORS.keys() and not chosen & EMULATORS.keys():
        raise ValueError('Select at least one emulator')
    for name in chosen:
        if not set(modules[name].get('available_with',[]))<=chosen:
            raise ValueError(modules[name]['label']+' requires mGBA')
    if 'developer' in chosen and ('ssh' not in chosen or not chosen & {'wifi','usb-network'}):
        raise ValueError('Developer Mode needs SSH and Wi-Fi or USB networking')
    return sorted(chosen)

def transfer_warning(chosen,destination):
    chosen=set(chosen)
    route=bool(chosen & {'usb-storage','external-sd'} or chosen & {'wifi','usb-network'} and chosen & {'ssh','sharing'})
    if route:return None
    if destination=='sd':return 'Copy games by removing this SD card and using a computer reader.'
    return 'No game-transfer route. Internal storage will need an external SD card or reinstall to add games.'

def info(path):
    st=path.lstat()
    if stat.S_ISLNK(st.st_mode):return {'type':'symlink','target':os.readlink(path),'mode':stat.S_IMODE(st.st_mode)}
    if stat.S_ISREG(st.st_mode):return {'type':'file','bytes':st.st_size,'sha256':digest(path),'mode':stat.S_IMODE(st.st_mode)}
    if stat.S_ISDIR(st.st_mode):return {'type':'directory','mode':stat.S_IMODE(st.st_mode)}
    raise ValueError('Unsupported module file type')

def check_tree(root,wanted):
    for name,entry in wanted.items():
        safe_name(name)
        p=Path(root)/name
        if not p.exists() and not p.is_symlink():raise ValueError('Missing installed module file: '+name)
        if info(p)!=entry:raise ValueError('Installed module file differs: '+name)

def unpack(archive,root,inventory):
    root=Path(root)
    with tarfile.open(archive,'r:gz') as t:
        members=t.getmembers()
        if len(members)!=len(inventory) or {m.name for m in members}!=set(inventory):raise ValueError('Module archive inventory differs')
        for m in members:
            p=PurePosixPath(m.name)
            if p.is_absolute() or '..' in p.parts or str(p)!=m.name or not (m.isfile() or m.issym() or m.isdir()):raise ValueError('Unsafe module archive member')
            dest=root/m.name
            # Never traverse a root or ancestor symlink, even for a trusted kit.
            if any(v.is_symlink() for v in [dest,*list(dest.parents)[:len(p.parts)-1]]):raise ValueError('Module extraction would follow a symlink')
            if dest.exists():raise ValueError('Module paths overlap the core')
            dest.parent.mkdir(parents=True,exist_ok=True)
            if m.issym():dest.symlink_to(m.linkname)
            elif m.isdir():dest.mkdir()
            else:
                with dest.open('xb') as f:shutil.copyfileobj(t.extractfile(m),f)
                dest.chmod(m.mode & 0o7777)
    check_tree(root,inventory)

def compose(kit,chosen,work,output,progress=None):
    kit,work,output=map(Path,(kit,work,output));catalog=load(kit);chosen=selection(catalog,chosen)
    progress=progress or (lambda text,pct:None)
    if work.exists() or work.is_symlink() or output.exists() or output.is_symlink():raise ValueError('Module composition requires fresh paths')
    work.mkdir(mode=0o700);root=work/'root'
    progress('Checking feature packages',78)
    for item in catalog['payloads']:
        p=kit/item['file']
        if p.is_symlink() or not p.is_file() or p.stat().st_size!=item['bytes'] or digest(p)!=item['sha256']:raise ValueError('Module payload failed verification')
    subprocess.run([str(kit/'tools/unsquashfs'),'-processors','2','-no-progress','-no-xattrs','-d',str(root),str(kit/'core.sfs')],check=True,stdout=subprocess.DEVNULL)
    expected=dict(catalog['core_inventory'])
    check_tree(root,expected)
    for package in catalog['packages']:
        if package['owners'] and not set(package['owners']) & set(chosen):continue
        unpack(kit/package['file'],root,package['inventory']);expected.update(package['inventory'])
    # Drop ordering and requirement edges to units that were not installed.
    # Remaining units keep their original dependencies and commands.
    absent={n for n in catalog.get('optional_units',[]) if not (root/'usr/lib/systemd/system'/n).exists()}
    for directory in ('usr/lib/systemd/system','etc/systemd/system'):
        for path in (root/directory).rglob('*'):
            if path.is_symlink() or not path.is_file():continue
            name=str(path.relative_to(root))
            if name not in expected:continue
            before=path.read_text();lines=[]
            for line in before.splitlines(keepends=True):
                key,sep,value=line.partition('=')
                if sep and key.strip() in {'After','Before','Wants','Requires','Requisite','BindsTo','PartOf'}:
                    names=value.split()
                    if any(n in absent for n in names):
                        line=key+'='+' '.join(n for n in names if n not in absent)+'\n'
                lines.append(line)
            after=''.join(lines)
            if before!=after:path.write_text(after);expected[name]=info(path)
    # Keep the selected immutable core set explicit in the boot/update contract.
    if {v['id'] for v in catalog['modules']} & EMULATORS.keys():
        cores=sorted(EMULATORS[name] for name in chosen if name in EMULATORS)
        system=root/'usr/share/slot/System'
        for filename in EMULATORS.values():
            if (system/filename).is_file() != (filename in cores):
                raise ValueError('Selected emulator payload differs: '+filename)
        declaration=system/'update-contract.json'
        contract=json.loads(declaration.read_text());contract['cores']=cores
        save(declaration,contract);expected[str(declaration.relative_to(root))]=info(declaration)
        profile_path=root/'usr/share/slot/os-profile.json'
        profile=json.loads(profile_path.read_text())
        for filename in EMULATORS.values():
            if filename not in cores:profile['factory_binaries'].pop(filename,None)
        for filename in cores:
            if profile['factory_binaries'].get(filename)!=digest(system/filename):
                raise ValueError('Selected emulator differs from factory profile')
        save(profile_path,profile);expected[str(profile_path.relative_to(root))]=info(profile_path)
    feature=root/'usr/share/slot/features-v1' 
    feature.write_text('slot-features-v1\n'+'\n'.join(chosen)+'\n');feature.chmod(0o644)
    expected['usr/share/slot/features-v1']=info(feature)
    # An update from a full firmware must not silently restore omitted features.
    optional={name:sorted(package['owners']) for package in catalog['packages'] for name in package['inventory'] if package['owners']}
    policy={'schema':1,'kit':catalog['id'],'selected':chosen,'known':sorted(m['id'] for m in catalog['modules']),'optional':optional}
    prefix='usr/share/slot/System/'
    frontend=dict(policy,optional={n[len(prefix):]:owners for n,owners in optional.items() if n.startswith(prefix)})
    save(root/'usr/share/slot/System/module-policy-v1.json',frontend)
    expected['usr/share/slot/System/module-policy-v1.json']=info(root/'usr/share/slot/System/module-policy-v1.json')
    save(root/'usr/share/slot/modules-v1.json',dict(policy,updates_preserve_modules_required=True))
    expected['usr/share/slot/modules-v1.json']=info(root/'usr/share/slot/modules-v1.json')
    progress('Building your selected system',88)
    subprocess.run([str(kit/'tools/mksquashfs'),str(root),str(output),'-comp','lz4','-Xhc','-b','65536','-noappend','-all-root','-no-xattrs','-no-progress','-processors','2','-mem','64M'],check=True,stdout=subprocess.DEVNULL)
    fd=os.open(output,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    syncdir(output.parent)
    # The compressed output is durable. Release the build tree before independently
    # extracting and checking it; a 512 MiB system filesystem must never need two
    # simultaneous unpacked Linux trees. A failed verification is not published.
    shutil.rmtree(root)
    progress('Checking the selected system',96)
    verify=work/'verify'
    subprocess.run([str(kit/'tools/unsquashfs'),'-processors','2','-no-progress','-no-xattrs','-d',str(verify),str(output)],check=True,stdout=subprocess.DEVNULL)
    check_tree(verify,expected)
    actual={str(p.relative_to(verify)) for p in verify.rglob('*') if p.is_file() or p.is_symlink()}
    wanted={n for n,v in expected.items() if v['type']!='directory'}
    if actual!=wanted:raise ValueError('Selected system has unexpected files')
    shutil.rmtree(verify)
    return {'schema':1,'kit':catalog['id'],'selected':chosen,'system_sha256':digest(output),'system_bytes':output.stat().st_size,'files':len(wanted)}
