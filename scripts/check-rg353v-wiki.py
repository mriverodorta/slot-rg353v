#!/usr/bin/env python3
"""Validate guide links, native media, durations and module explanation coverage.

Host documentation check only: never contacts the device or network.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from urllib.parse import unquote
from wiki.boot_timing import load_timing, quantized_events

ROOT=Path(__file__).resolve().parents[1]
WIKI=ROOT/'wiki'
errors=[]
links=0
for page in sorted(WIKI.glob('*.md')):
    text=page.read_text()
    # Exclude code fences; include image links and links inside details sections.
    text=re.sub(r'```.*?```','',text,flags=re.S)
    for value in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',text):
        target=value.strip().strip('<>')
        if re.match(r'^[a-z]+:',target):continue
        name,_,anchor=target.partition('#')
        path=(page.parent/unquote(name)).resolve() if name else page
        links+=1
        if not path.exists():errors.append(f'{page.name}: missing {target}')
        if anchor and path.suffix=='.md' and path.exists():
            headings=re.findall(r'^#{1,6}\s+(.+)$',path.read_text(),flags=re.M)
            slugs={re.sub(r'[^\w\- ]','',h.lower()).replace(' ','-') for h in headings}
            if unquote(anchor) not in slugs:errors.append(f'{page.name}: missing heading {target}')

manifest=json.loads((WIKI/'media/manifest.json').read_text())
timing=load_timing(ROOT)
boot_duration_ms=sum(duration for _,duration in quantized_events(timing))
boot_info=manifest['boot_animation']
if boot_info.get('timing_sha256')!=hashlib.sha256((WIKI/'media/boot-timing.json').read_bytes()).hexdigest():
    errors.append('Changed boot presentation trace')
if boot_info.get('mp4_fps')!=60:errors.append('Boot MP4 must preserve the short handoff at 60 fps')
for relative,expected in manifest.get('render_inputs',{}).items():
    path=ROOT/relative
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        errors.append('Stale media render input: '+relative)
if not manifest.get('render_inputs'):errors.append('Missing media render-input provenance')
actual={str(p.relative_to(WIKI)) for directory in (WIKI/'images',WIKI/'media')
        for p in directory.rglob('*') if p.suffix in ('.png','.gif','.mp4')}
if actual!=set(manifest['files']):errors.append('Media manifest file set differs from actual assets')
for relative,row in manifest['files'].items():
    p=WIKI/relative
    if not p.is_file():errors.append('Missing media: '+relative);continue
    data=p.read_bytes()
    if hashlib.sha256(data).hexdigest()!=row['sha256']:errors.append('Changed media: '+relative)
    if len(data)!=row['bytes']:errors.append('Wrong size: '+relative)
    if p.suffix=='.png':
        if data[:8]!=b'\x89PNG\r\n\x1a\n' or struct.unpack('>II',data[16:24])!=(640,480):
            errors.append('Wrong PNG dimensions: '+relative)
    if p.suffix=='.gif':
        if data[:6] not in (b'GIF87a',b'GIF89a') or struct.unpack('<HH',data[6:10])!=(640,480):
            errors.append('Wrong GIF dimensions: '+relative)
        if 'boot-to-shelf' in p.name and row.get('duration_ms')!=boot_duration_ms:
            errors.append('Boot animation duration differs from the captured trace')

catalog=json.loads((ROOT/'ports/rg353v/modules/catalog-v1.json').read_text())
index=(WIKI/'Screens-and-Media.md').read_text()
for module in catalog['modules']:
    asset='images/setup/info-'+module['id']+'.png'
    if asset not in actual or asset not in index:errors.append('Missing feature explanation: '+module['id'])
    if module['description'] not in index:errors.append('Stale feature explanation: '+module['id'])

# Reject common accidental private identities in public guide text/metadata.
for p in list(WIKI.glob('*.md'))+list((WIKI/'media').glob('*.json')):
    text=p.read_text()
    for marker in ('BEGIN OPENSSH PRIVATE KEY','BEGIN PRIVATE KEY','ssh-ed25519 AAAA',
                   '/Users/', '/home/'):
        if marker in text:errors.append(f'{p.name}: private marker {marker!r}')
if errors:
    print('\n'.join(errors),file=sys.stderr);sys.exit(1)
total=sum(row['bytes'] for row in manifest['files'].values())
print(f'PASS {len(list(WIKI.glob("*.md")))} Markdown pages, {links} local links, '
      f'{len(actual)} media assets, {len(catalog["modules"])} module explanations; '
      f'{total/1024/1024:.2f} MiB media, measured shelf swap {timing["shelf_swap_s"]:.3f} s; '
      f'GIF {boot_duration_ms/1000:.3f} s including shelf hold.')
