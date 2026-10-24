#!/usr/bin/env python3
"""Build a bounded copy/literal OS patch from two qualified OS capsules."""
import argparse
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('slot_os_delta',str(ROOT/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-os-update'))
spec=importlib.util.spec_from_loader(loader.name,loader)
o=importlib.util.module_from_spec(spec);loader.exec_module(o)
u=o.u
GEAR=tuple(int.from_bytes(hashlib.sha256(bytes([n])).digest()[:8],'little') for n in range(256))
MINIMUM,MAXIMUM,MASK=16*1024,256*1024,(1<<16)-1


def chunks(path):
    """Content-defined boundaries resynchronize after inserted/deleted bytes."""
    offset=0
    with Path(path).open('rb') as source:
        while block:=source.read(MAXIMUM):
            rolling=0;cut=len(block)
            for index in range(MINIMUM,len(block)):
                rolling=((rolling<<1)+GEAR[block[index]])&((1<<64)-1)
                if rolling&MASK==0:
                    cut=index+1;break
            data=block[:cut]
            yield offset,data
            offset+=cut;source.seek(offset)


def unpack(package,root):
    with tarfile.open(package,'r:*') as archive:
        entries=archive.getmembers()
        u.require(len(entries)<=10000 and all(m.isfile() for m in entries)
                  and len({m.name for m in entries})==len(entries), 'Invalid input capsule members')
        meta=json.load(archive.extractfile('manifest.json'))
        u.require(meta.get('schema')==1 and meta.get('kind')=='os'
                  and meta.get('target')=={'device':'rg353v','arch':'aarch64'}, 'Build deltas from full RG353V OS capsules')
        inventory=meta['files']
        u.require(set(archive.getnames())=={'manifest.json'}|{'payload/'+n for n in inventory}
                  and sum(m.size for m in entries)<=o.MAX_OS_BYTES, 'Input capsule inventory mismatch')
        for name,info in inventory.items():
            u.require(o.payload_name(name), 'Invalid input boot path')
            member=archive.getmember('payload/'+name)
            u.require(member.size==info['size'], 'Input capsule size mismatch')
            dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as source,dest.open('xb') as target:
                o.shutil.copyfileobj(source,target)
            u.require(u.sha(dest)==info['sha256'], 'Input capsule checksum mismatch')
    return meta


def recipe(base,target,literals):
    index={}
    if base is not None:
        for offset,data in chunks(base):
            index.setdefault(hashlib.sha256(data).digest(),(offset,len(data)))
    operations=[];reused=0
    with literals.open('xb') as out:
        for _,data in chunks(target):
            match=index.get(hashlib.sha256(data).digest())
            if match is not None:
                offset,length=match;kind='copy';reused+=length
            else:
                offset,length=out.tell(),len(data);kind='data';out.write(data)
            if operations and operations[-1][0]==kind and operations[-1][1]+operations[-1][2]==offset:
                operations[-1][2]+=length
            else:operations.append([kind,offset,length])
    return operations,reused


def package(base,target,output):
    output=Path(output)
    u.require(not output.exists() and not output.with_name(output.name+'.partial').exists(), 'Output already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    partial=output.with_name(output.name+'.partial')
    try:
        with tempfile.TemporaryDirectory(prefix='slot-os-delta-') as work:
            work=Path(work);old=work/'old';new=work/'new';patches=work/'patch'
            old.mkdir();new.mkdir();patches.mkdir()
            previous=unpack(base,old);meta=unpack(target,new)
            meta.update(schema=2,base_runtime=previous['runtime'],base_files=previous['files'],recipes={},patches={})
            reused=0
            for name in sorted(meta['files']):
                patch=patches/name;patch.parent.mkdir(parents=True,exist_ok=True)
                source=old/name if name in previous['files'] else None
                operations,retained=recipe(source,new/name,patch)
                meta['recipes'][name]=operations;reused+=retained
                if patch.stat().st_size:
                    meta['patches'][name]={'size':patch.stat().st_size,'sha256':u.sha(patch)}
            raw=(json.dumps(meta,sort_keys=True,separators=(',',':'))+'\n').encode()
            u.require(len(raw)<=1024**2,'OS delta manifest exceeds size limit')
            with tarfile.open(partial,'w:gz',compresslevel=6) as archive:
                member=tarfile.TarInfo('manifest.json');member.size=len(raw)
                archive.addfile(member,io.BytesIO(raw))
                for name in sorted(meta['patches']):archive.add(patches/name,arcname='patch/'+name,recursive=False)
            with partial.open('rb') as stream:os.fsync(stream.fileno())
            partial.replace(output);u.syncdir(output.parent)
        stats={'package':str(output),'sha256':u.sha(output),'download_bytes':output.stat().st_size,
               'full_package_bytes':Path(target).stat().st_size,'reused_bytes':reused,
               'literal_bytes':sum(v['size'] for v in meta['patches'].values()),
               'reconstructed_bytes':sum(v['size'] for v in meta['files'].values())}
        output.with_name(output.name+'.sha256').write_text(stats['sha256']+'  '+output.name+'\n')
        return stats
    finally:partial.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True,help='Qualified full capsule matching the installed boot files')
    parser.add_argument('--target',type=Path,required=True,help='Qualified full capsule for the same installed module selection')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(package(args.base,args.target,args.output),indent=2))


if __name__=='__main__':main()
