#!/usr/bin/env python3
"""Record built package closure, file sizes and firmware payload hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--tree',type=Path,required=True)
p.add_argument('--profile',choices=['normal','development','legacy'],required=True)
p.add_argument('--seconds',type=int,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
build=a.tree/'build.ROCKNIX-RK3566.aarch64';root=build/'image/system'
def digest(stream):
 h=hashlib.sha256()
 for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
packages=sorted(x.name for x in (build/'image/.stamps').iterdir() if x.is_dir())
files={}
for f in sorted(root.rglob('*')):
 if f.is_file() and not f.is_symlink():files[str(f.relative_to(root))]={'bytes':f.stat().st_size}
artifacts={}
for f in sorted((a.tree/'target').glob('*')):
 if f.suffix=='.tar' or f.name.endswith('.img.gz'):
  with f.open('rb') as stream:sha=digest(stream)
  item={'bytes':f.stat().st_size,'sha256':sha}
  if f.suffix=='.tar':
   with tarfile.open(f) as archive:
    item['payload']={}
    for member in archive:
     if member.isfile() and member.name.endswith(('/target/KERNEL','/target/SYSTEM')):
      with archive.extractfile(member) as stream:sha=digest(stream)
      item['payload'][Path(member.name).name]={'bytes':member.size,'sha256':sha}
  artifacts[f.name]=item
factory=root/'usr/share/slot/os-profile.json'
factory_profile=json.loads(factory.read_text())
checks={}
tools=a.tree/'projects/ROCKNIX/devices/RK3566/packages/slot-startup-profile/tools'
if factory_profile.get('kernel_profile','baseline') != 'baseline':
 if factory_profile['kernel_profile'] != 'rg353v-slim-v1':raise ValueError('Unknown built kernel profile')
 config=build/'build/linux-7.0.2/.config'
 subprocess.run(['python3',str(tools/'configure-kernel.py'),'--validate',str(config)],check=True)
 modules=root/'usr/lib/kernel-overlays/base/lib/modules/7.0.2'
 required=['mali_kbase.ko','rocknix-singleadc-joypad.ko','rtw88_8821cs.ko','rtw88_8821c.ko','rtw88_sdio.ko','rtw88_core.ko']
 built_modules=list(modules.rglob('*.ko'))
 if not set(required)<={p.name for p in built_modules}:raise ValueError('Missing required board module')
 if any('/bluetooth/' in str(p) or p.name in ('hantro-vpu.ko','hantro_vpu.ko','rockchip-rga.ko','rockchip_rga.ko') for p in built_modules):
  raise ValueError('Unused Bluetooth/video modules remain in slim image')
 with config.open('rb') as stream:config_sha=digest(stream)
 checks['kernel']={'profile':'rg353v-slim-v1','resolved_config_sha256':config_sha,'required_modules':'passed','unused_modules':'absent'}
if factory_profile.get('userspace_profile','baseline') != 'baseline':
 if factory_profile['userspace_profile'] != 'rg353v-lean-v1':raise ValueError('Unknown built userspace profile')
 subprocess.run(['python3',str(tools/'configure-userspace.py'),'--tree',str(a.tree),'--validate'],check=True)
 audit=a.output.parent/'elf-audit.json'
 subprocess.run(['python3',str(Path(__file__).with_name('audit-rg353v-image.py')),'--root',str(root),'--output',str(audit)],check=True)
 inventory=json.loads(audit.read_text())
 if inventory['missing_needed_names']:raise ValueError('Unresolved shared-library names in lean image')
 if inventory['userspace_32bit']:raise ValueError('Unexpected 32-bit userspace in RG353V lean image')
 checks['userspace']={'profile':'rg353v-lean-v1','package_closure':'passed','sdl_build_options':'passed'}
result={'schema':1,'profile':a.profile,'elapsed_seconds':a.seconds,'packages':packages,'package_count':len(packages),'files':files,'root_regular_bytes':sum(x['bytes'] for x in files.values()),'artifacts':artifacts,'factory_profile':factory_profile,'trial_checks':checks}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({'profile':a.profile,'seconds':a.seconds,'packages':len(packages),'root_regular_bytes':result['root_regular_bytes'],'report':str(a.output)}))
