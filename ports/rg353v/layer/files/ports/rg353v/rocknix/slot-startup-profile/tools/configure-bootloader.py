#!/usr/bin/env python3
"""Freeze reviewed U-Boot build metadata without changing its hardware behavior."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

HERE = Path(__file__).resolve().parent
MARKER = '# Generated RG353V reproducible bootloader metadata;'


def set_fit_timestamp(path, epoch):
    """Change the existing root timestamp in place; preserve external FIT data.

    mkimage -F can repack external images, changing their layout. This updates
    only the existing four-byte metadata value, never payloads or their hashes.
    """
    if not 0 <= epoch <= 0xffffffff:
        raise ValueError('FIT epoch must fit an unsigned 32-bit timestamp')
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular built FIT image')
    blob = bytearray(path.read_bytes())
    if len(blob) < 40:
        raise ValueError('Truncated FIT header')
    magic,total,off_structure,off_strings,_,version,compatible,_,strings_size,structure_size = struct.unpack_from('>10I',blob)
    end = off_structure + structure_size
    if (magic != 0xd00dfeed or version != 17 or compatible > 17 or total > len(blob)
            or off_structure < 40 or off_strings < end or end > total
            or off_strings+strings_size > total):
        raise ValueError('Unsupported FIT structure')
    strings = blob[off_strings:off_strings+strings_size]
    position,depth,offsets = off_structure,0,[]
    finished = False
    while position+4 <= end:
        token = struct.unpack_from('>I',blob,position)[0];position += 4
        if token == 1:
            terminator = blob.find(0,position,end)
            if terminator < 0: raise ValueError('Invalid FIT node')
            position = (terminator+4)&~3;depth += 1
        elif token == 2:
            depth -= 1
            if depth < 0: raise ValueError('Unbalanced FIT node')
        elif token == 3:
            if position+8 > end: raise ValueError('Truncated FIT property')
            size,name_offset = struct.unpack_from('>2I',blob,position);position += 8
            terminator = strings.find(0,name_offset)
            if position+size > end or name_offset >= len(strings) or terminator < 0:
                raise ValueError('Invalid FIT property')
            if depth == 1 and strings[name_offset:terminator] == b'timestamp':
                if size != 4: raise ValueError('Unexpected FIT timestamp size')
                offsets.append(position)
            position = (position+size+3)&~3
        elif token == 4:
            pass
        elif token == 9:
            finished = depth == 0
            break
        else:
            raise ValueError('Unknown FIT structure token')
    if not finished or len(offsets) != 1:
        raise ValueError('Expected one existing root FIT timestamp')
    struct.pack_into('>I',blob,offsets[0],epoch)
    path.write_bytes(blob)


def stage(tree, policy_path=None):
    policy = json.loads((policy_path or HERE.parent/'config/bootloader-build.json').read_text())
    if policy['schema'] != 1: raise ValueError('Unsupported bootloader build policy')
    planned = []
    for name,entry in policy['recipes'].items():
        if name not in ('u-boot-Generic','u-boot-Specific'):
            raise ValueError('Unsupported bootloader recipe')
        recipe = tree/'projects/ROCKNIX/devices/RK3566/packages'/name/'package.mk'
        original = recipe.read_text().split('\n'+MARKER,1)[0]
        if hashlib.sha256(original.encode()).hexdigest() != entry['source_sha256']:
            raise ValueError('Review changed upstream bootloader recipe: '+name)
        hooks = re.findall(r'^make_target\(\) \{\n.*?^\}',original,re.M|re.S)
        if len(hooks) != 1: raise ValueError('Review bootloader make contract')
        if not re.fullmatch(r'[0-9a-f]{64}',entry['output_sha256']):
            raise ValueError('Invalid bootloader output identity')
        compiler_epoch,fit_epoch = entry['compiler_epoch'],entry['fit_epoch']
        if any(type(n) is not int or not 0 <= n <= 0xffffffff for n in (compiler_epoch,fit_epoch)):
            raise ValueError('Invalid bootloader metadata epoch')
        hook = hooks[0].replace('make_target() {','slot_upstream_make_target() {',1)
        text = (original+'\n'+MARKER+'\n'+hook+'\n\nmake_target() (\n'
                f'  export SOURCE_DATE_EPOCH={compiler_epoch}\n'
                '  slot_upstream_make_target\n'
                '  python3 "${PROJECT_DIR}/${PROJECT}/devices/RK3566/packages/slot-startup-profile/tools/configure-bootloader.py"'
                f' --fit "${{PKG_BUILD}}/u-boot.itb" --epoch {fit_epoch}\n'
                '  rm -f uboot.bin idbloader.img\n'
                '  find_file_path bootloader/rkhelper && . ${FOUND_PATH}\n'
                f'  [ "$(sha256sum uboot.bin | cut -d " " -f 1)" = "{entry["output_sha256"]}" ] || '
                '{ echo "Rebuilt loader identity differs; review required." >&2; return 1; }\n)\n')
        planned.append((recipe,text))
    for recipe,text in planned: recipe.write_text(text)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--tree',type=Path)
    group.add_argument('--fit',type=Path)
    p.add_argument('--epoch',type=int)
    a=p.parse_args()
    if a.fit:
        if a.epoch is None: p.error('--fit requires --epoch')
        set_fit_timestamp(a.fit,a.epoch)
    else:
        if a.epoch is not None: p.error('--epoch is only valid with --fit')
        stage(a.tree)
