#!/usr/bin/env python3
"""Prepare local GitHub Wiki pages with explicit page/source/image URLs. No upload."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

LINK = re.compile(r'(!?\[[^\]\n]*\])\(([^)\n]+)\)')
def rewrite(text, page, wiki, repository, ref):
    base='https://github.com/'+repository
    root=wiki.parent.resolve()
    def link(match):
        label, target = match.groups(); url=urlsplit(target.strip().strip('<>'))
        if url.scheme or url.netloc or not url.path: return match[0]
        destination=(page.parent/unquote(url.path)).resolve()
        if destination != root and root not in destination.parents:
            raise ValueError('Documentation link escapes source repository')
        if not destination.is_file(): raise ValueError('Missing documentation target: '+url.path)
        relative=destination.relative_to(root).as_posix()
        if destination.parent==wiki.resolve() and destination.suffix=='.md':
            address=base+'/wiki/'+quote(destination.stem.replace(' ','-'),safe='-_.')
        elif label.startswith('!'):
            if destination.suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.webp'):
                raise ValueError('Use inline image/GIF media; no video download links')
            address='https://raw.githubusercontent.com/'+repository+'/'+quote(ref,safe='')+'/'+quote(relative,safe='/')
        else:
            if destination.suffix.lower() in ('.mp4','.mov','.webm'):
                raise ValueError('Video download links are not part of the guide')
            address=base+'/blob/'+quote(ref,safe='')+'/'+quote(relative,safe='/')
        if url.query: address+='?'+url.query
        if url.fragment: address+='#'+url.fragment
        return label+'('+address+')'
    # Examples inside fenced code blocks must remain copyable and unchanged.
    chunks=re.split(r'(```.*?```)',text,flags=re.S)
    return ''.join(chunk if i%2 else LINK.sub(link,chunk) for i,chunk in enumerate(chunks))

def export(wiki, output, repository, ref):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repository): raise ValueError('Use owner/repository')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',ref) or '..' in ref: raise ValueError('Use an explicit simple tag, commit or branch')
    wiki=wiki.resolve(strict=True);output=output.resolve()
    if output.exists(): raise ValueError('Wiki export output must be fresh')
    if output==wiki or wiki in output.parents: raise ValueError('Keep exports outside the versioned guide')
    pages={p.name:rewrite(p.read_text(),p,wiki,repository,ref) for p in sorted(wiki.glob('*.md'))}
    if not {'Home.md','_Sidebar.md','_Footer.md'} <= pages.keys(): raise ValueError('Wiki needs Home, sidebar and footer')
    output.mkdir(parents=True)
    for name,text in pages.items():(output/name).write_text(text)
    return {'schema':1,'repository':repository,'source_ref':ref,'pages':len(pages),
            'files':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in pages.items()},
            'publication':'Local export only. No network/Git upload. Candidate qualification, source/license checks and third-party artwork notices still apply.'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wiki',type=Path,default=Path(__file__).resolve().parents[1]/'wiki')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repository',default='mriverodorta/slot-rg353v')
    p.add_argument('--ref',required=True,help='Reviewed source tag/commit; main may be used for local preview')
    p.add_argument('--report',type=Path)
    a=p.parse_args();report=export(a.wiki,a.output,a.repository,a.ref)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('repository','source_ref','pages','publication')}))
if __name__=='__main__':main()
