#!/usr/bin/env python3
"""Read-only installed-image inventory; dependency findings are not deletion approval."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def target(root, relative):
    """Resolve image links in the image namespace, never in the host's /usr."""
    parts = list(Path(relative).parts)
    current = []
    links = 0
    while parts:
        piece = parts.pop(0)
        if piece in ('', '/', '.'):
            continue
        if piece == '..':
            if not current:
                raise ValueError('Image path escapes root')
            current.pop()
            continue
        path = root.joinpath(*current, piece)
        if path.is_symlink():
            links += 1
            if links > 40:
                raise ValueError('Image symlink loop')
            link = path.readlink()
            if link.is_absolute():
                current = []
            parts = list(link.parts) + parts
        else:
            current.append(piece)
    return root.joinpath(*current)


def elf(path):
    with path.open('rb') as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b'\x7fELF':
        return None
    order = {1: '<', 2: '>'}.get(header[5])
    if not order or header[4] not in (1, 2):
        raise ValueError('Unsupported ELF encoding: '+str(path))
    kind,machine = struct.unpack_from(order+'HH',header,16)
    if kind not in (2,3):
        return None  # Exclude kernel modules and firmware relocatable objects.
    raw = subprocess.run(['readelf','--wide','--dynamic',str(path)],capture_output=True,text=True,check=True).stdout
    return {'class':32 if header[4]==1 else 64,'machine':machine,
            'needed':re.findall(r'\(NEEDED\).*?\[(.*?)\]',raw),
            'soname':next(iter(re.findall(r'\(SONAME\).*?\[(.*?)\]',raw)),None),
            'runpath':re.findall(r'\((?:RUNPATH|RPATH)\).*?\[(.*?)\]',raw)}


def inspect(root):
    root = root.resolve()
    files, binaries, aliases = {}, {}, {}
    firmware = Counter()
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        files[name] = path.stat().st_size
        # Firmware may itself be ELF, but it is not a userspace executable.
        if '/firmware/' in '/'+name:
            key = name.split('/firmware/',1)[1].split('/')[0]
            firmware[key] += files[name]
            continue
        info = elf(path)
        if info:
            binaries[name] = info
            aliases.setdefault(path.name,[]).append(name)
            if info['soname']:
                aliases.setdefault(info['soname'],[]).append(name)
    for path in root.rglob('*'):
        if not path.is_symlink():
            continue
        try:
            dest = target(root,path.relative_to(root)).relative_to(root).as_posix()
        except ValueError:
            continue
        if dest in binaries:
            aliases.setdefault(path.name,[]).append(dest)
    absent = {n:sorted({lib for lib in info['needed'] if lib not in aliases})
              for n,info in binaries.items()}
    absent = {n:v for n,v in absent.items() if v}
    critical = {}
    for name in ('slot','mgba_libretro.so','gpsp_libretro.so'):
        p=root/'usr/share/slot/System'/name
        if p.is_file():
            critical[name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                            'needed':binaries.get(p.relative_to(root).as_posix(),{}).get('needed',[])}
    return {'schema':1,'read_only':True,'root_regular_bytes':sum(files.values()),
            'file_count':len(files),'userspace_elf_count':len(binaries),
            'userspace_32bit':[n for n,i in binaries.items() if i['class']==32],
            'missing_needed_names':absent,'critical_binaries':critical,
            'largest_files':[{'path':n,'bytes':b} for n,b in sorted(files.items(),key=lambda x:x[1],reverse=True)[:50]],
            'firmware_bytes_by_family':dict(firmware.most_common()),
            'elf':binaries,
            'limits':'DT_NEEDED name inventory does not prove dlopen usage, loader search order, ABI compatibility, or safe deletion.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve() == args.root.resolve() or args.root.resolve() in args.output.resolve().parents:
        parser.error('Report output must be outside the inspected image')
    result=inspect(args.root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k in ('root_regular_bytes','file_count','userspace_elf_count','userspace_32bit','missing_needed_names')}))
