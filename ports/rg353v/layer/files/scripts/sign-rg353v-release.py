#!/usr/bin/env python3
"""Create signed release metadata; the private key stays outside the repository."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('package', type=Path, nargs='*')
p.add_argument('--catalog', action='store_true', help='Publish a schema-2 catalog of base-specific delta variants')
p.add_argument('--output-dir', type=Path, help='Required for an empty initial catalog; otherwise the package directory')
p.add_argument('--head', action='append', default=[], help='Final target package ID; repeat for qualified installation variants. Required for mixed OS/component catalogs')
p.add_argument('--key', type=Path, required=True)
p.add_argument('--sequence', type=int, required=True)
p.add_argument('--notes', default='')
p.add_argument('--days', type=int, default=7)
args = p.parse_args()
if not 1 <= args.days <= 31 or args.sequence <= 0:
    p.error('Use positive sequence and validity of 1–31 days')
now = int(time.time())
if not args.catalog and len(args.package)!=1:p.error('Multiple variants require --catalog')
if not args.package and (not args.catalog or args.output_dir is None):
    p.error('An empty catalog requires --catalog and --output-dir')
if len({v.name for v in args.package})!=len(args.package):p.error('Artifact filenames must be unique')
if len({v.resolve().parent for v in args.package})>1:p.error('Keep all catalog artifacts in the same release directory')
directory=args.output_dir or args.package[0].parent
if args.package and any(v.resolve().parent!=directory.resolve() for v in args.package):
    p.error('--output-dir must be the package directory')
if not directory.is_dir():p.error('Output directory must exist')
packages=[]
for package in args.package:
    with tarfile.open(package) as archive:
        inside=json.load(archive.extractfile('manifest.json'))
    digest=hashlib.sha256()
    with package.open('rb') as source:
        for block in iter(lambda:source.read(1024**2),b''):digest.update(block)
    descriptor={'id':inside['id'],'kind':inside['kind'],'file':package.name,
                'size':package.stat().st_size,'sha256':digest.hexdigest()}
    if args.catalog:
        if inside.get('schema')!=2:p.error('Catalog variants require schema-2 delta packages')
        if inside['kind']=='os':
            descriptor['requires']={'runtime':inside['base_runtime'],'boot_files':inside['base_files']}
            descriptor['provides']={'runtime':inside['runtime'],'revision':'os-'+inside['id'],
                                    'boot_files':inside['files']}
        else:
            policy=inside.get('modules')
            descriptor['requires']={'runtime':inside['runtime'],'revision':inside['base'],
                                    'inventory_sha256':inside['base_sha256'],
                                    'modules':sorted(policy['selected']) if policy else None}
            descriptor['provides']={'runtime':inside['runtime'],'revision':inside['id'],
                                    'inventory_sha256':inside['target_sha256'],
                                    'modules':sorted(policy['selected']) if policy else None}
    packages.append(descriptor)
meta = {'schema': 1, 'target': {'device': 'rg353v', 'arch': 'aarch64'},
        'sequence': args.sequence, 'issued': now, 'expires': now + args.days * 86400,
        'notes': args.notes}
if args.catalog:
    if args.head and not set(args.head) <= {v['id'] for v in packages}:
        p.error('--head must name a supplied target package')
    if not args.head and any(v['kind']=='os' for v in packages) and any(v['kind']!='os' for v in packages):
        p.error('Mixed OS/component catalogs require explicit --head targets')
    def followed(target):
        for package in packages:
            rule=package['requires']
            if rule['runtime']!=target['runtime']:continue
            if rule.get('revision')==target['revision']:return True
            if 'boot_files' in target and rule.get('boot_files')==target['boot_files']:return True
        return False
    heads=[v['provides'] for v in packages if
           (v['id'] in args.head if args.head else not followed(v['provides']))]
    heads=list({json.dumps(v,sort_keys=True):v for v in heads}.values())
    if packages and not heads:p.error('Catalog has no final upgrade target; check for a cycle')
    meta.update(schema=2,packages=packages,heads=heads)
else:meta['package']=packages[0]
raw=json.dumps(meta,sort_keys=True,indent=2)+'\n'
if len(raw.encode())>64*1024:p.error('Release metadata exceeds the client 64 KiB limit')
output = directory / 'release.json'
output.write_text(raw)
subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(args.key),
                '-in', str(output), '-out', str(output) + '.sig'], check=True)
print('Signed release metadata:', output)
