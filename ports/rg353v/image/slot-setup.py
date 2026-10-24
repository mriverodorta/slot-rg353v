#!/usr/bin/env python3
"""RG353V first-boot destination chooser and journaled clean eMMC installer."""
import argparse
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import uuid

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('clean',HERE/'slot-clean-firstboot.py')
clean=importlib.util.module_from_spec(spec);spec.loader.exec_module(clean)
card,emmc=clean.card,clean.emmc
MIB=1024**2
LOADER_SHA='34349d124e47038a3203ca9cb69c8394a109adf008d250f3f8965539f8a2fb06'
LOADER_BYTES=9991680
JOURNAL='.slot-internal-install'


def run(*args):return clean.run(*args)


def identity(disk,test=False):
    if not stat.S_ISBLK(disk.stat().st_mode) or run('blockdev','--getss',disk)!='512':
        raise ValueError('Unsupported installation device')
    if test:
        if os.environ.get('SLOT_CLEAN_TEST')!='1' or not re.fullmatch(r'/dev/loop\d+',str(disk)):
            raise ValueError('Tests require explicit loop devices')
    elif not re.fullmatch(r'/dev/mmcblk\d+',str(disk)):
        raise ValueError('Unexpected MMC device')
    node=Path('/sys/class/block')/disk.name
    major,minor=map(int,(node/'dev').read_text().split(':'))
    if disk.stat().st_rdev!=os.makedev(major,minor):raise ValueError('Device node identity changed')
    total=int(run('blockdev','--getsize64',disk))
    if total < clean.STARTER_MIB*MIB:raise ValueError('Device cannot hold the installer')
    content=emmc.geometry(total)[3][1] if total>=8*1024**3 else None
    result={'device':str(disk),'bytes':total,'content_bytes':content,'layout':dict(emmc.DEFAULT_LAYOUT)}
    if test:
        result.update(type='loop',serial=(node/'loop/backing_file').read_text().strip())
    else:
        result.update(type=(node/'device/type').read_text().strip(),
                      serial=(node/'device/serial').read_text().strip())
        if not result['serial']:raise ValueError('Storage serial is unavailable')
    return result


def target_guard(source,target,expected,test=False):
    current=identity(target,test)
    if current!=expected or source.resolve()==target.resolve() or source.stat().st_rdev==target.stat().st_rdev:
        raise ValueError('Installation destination changed or is the boot source')
    if current['content_bytes'] is None:raise ValueError('Internal storage cannot hold the system layout')
    if not test and (current['type']!='MMC' or identity(source)['type']!='SD'):
        raise ValueError('Internal installation requires an SD source and eMMC target')
    if clean.mounted_on_disk(target):raise ValueError('Internal storage is mounted')
    node=Path('/sys/class/block')/target.name
    for part in [node,*node.glob(target.name+'p*')]:
        if (part/'holders').is_dir() and list((part/'holders').iterdir()):
            raise ValueError('Internal storage is in use')
    return current


def discover_target(source):
    found=[]
    for node in Path('/sys/class/block').glob('mmcblk*'):
        if re.fullmatch(r'mmcblk\d+',node.name) and (node/'device/type').read_text().strip()=='MMC':
            disk=Path('/dev')/node.name
            try:
                info=identity(disk);target_guard(source,disk,info);found.append(info)
            except (OSError,ValueError,subprocess.CalledProcessError):continue
    return found[0] if len(found)==1 else None


def confirmation(target):return 'ERASE-INTERNAL:'+target['serial']+':'+str(target['bytes'])


def new_plan():
    serial=secrets.token_hex(4).upper()
    return {'schema':clean.PLAN_SCHEMA,'kind':'slot-clean-firstboot','initial':dict(clean.INITIAL),
            'final':dict(clean.FINAL),'disk_guid':str(uuid.uuid4()),
            'boot_uuid':serial[:4]+'-'+serial[4:],'storage_uuid':str(uuid.uuid4()),
            'partition_guids':{str(n):str(uuid.uuid4()) for n in (1,2,3)}}


def loader(directory):
    info=json.loads((directory/'slot-installer-loader.json').read_text())
    binary=directory/'slot-installer-loader.bin'
    if (info.get('schema')!=1 or info.get('target')!='rg353v-panel-v2'
            or info.get('sha256')!=LOADER_SHA or info.get('bytes')!=LOADER_BYTES
            or info.get('offset')!=32768 or info.get('emmc_select') is not True
            or info.get('sd_clock_fix') is not True or binary.stat().st_size!=LOADER_BYTES
            or emmc.digest(binary)!=LOADER_SHA):
        raise ValueError('The validated RG353V recovery bootloader is missing or changed')
    return binary


def remove_mappings(disk):
    if clean.mounted_on_disk(disk):raise ValueError('Cannot replace mounted partitions')
    nodes=[p for p in Path('/sys/class/block').glob(disk.name+'p*') if re.fullmatch(disk.name+r'p\d+',p.name)]
    for node in sorted(nodes,key=lambda n:int(n.name.split('p')[-1]),reverse=True):
        number=int(node.name.split('p')[-1]);major,minor=map(int,(node/'dev').read_text().split(':'))
        device=Path('/dev')/node.name
        if device.exists() and (not stat.S_ISBLK(device.stat().st_mode) or device.stat().st_rdev!=os.makedev(major,minor)):
            raise ValueError('Unexpected old partition node')
        part=card.Partition(0,0,number);arg=card.PartitionArgument(2,0,ctypes.sizeof(part),ctypes.addressof(part))
        fd=os.open(disk,os.O_RDWR|os.O_CLOEXEC)
        try:
            if ctypes.CDLL(None,use_errno=True).ioctl(fd,0x1269,ctypes.byref(arg)):
                error=ctypes.get_errno();raise OSError(error,os.strerror(error))
        finally:os.close(fd)
        device.unlink(missing_ok=True)


def check_table(disk,plan,total):
    guid,parts=card.table(disk);desired=clean.final_geometry(plan,total)
    if guid!=plan['disk_guid'] or set(parts)!={1,2,3}:raise ValueError('Internal GPT identity changed')
    for n,(start,count) in desired.items():
        if (parts[n]['start'],parts[n]['bytes'],parts[n]['guid'])!=(start,count,plan['partition_guids'][str(n)]):
            raise ValueError('Internal partition geometry changed')


def boot_tree(source,destination,plan,durable=False,payload=None):
    config=destination/'extlinux/extlinux.conf'
    if durable:
        if payload is None:raise ValueError('A boot payload inventory is required')
        config.unlink(missing_ok=True);run('sync')
    for entry in source.iterdir():
        if entry.name in clean.HOOKS or entry.name=='extlinux':continue
        dest=destination/entry.name
        shutil.copytree(entry,dest,dirs_exist_ok=True) if entry.is_dir() else shutil.copyfile(entry,dest)
    if durable:
        run('sync')
        wanted={k:v for k,v in payload.items() if k not in clean.HOOKS and not k.startswith('extlinux/')}
        clean.check_inventory(destination,wanted)
    config.parent.mkdir(exist_ok=True)
    config.write_text(
        'LABEL Slot-Internal\n  LINUX /KERNEL\n  FDT /device_trees/rk3566-anbernic-rg353v.dtb\n'
        f'  APPEND boot=UUID={plan["boot_uuid"]} disk=UUID={plan["storage_uuid"]} quiet console=ttyS2,1500000\n')
    if durable:run('sync')


def backup_extent(disk,destination,offset,length):
    with disk.open('rb') as src,destination.open('xb') as out:
        os.fchmod(out.fileno(),0o600)
        src.seek(offset)
        for n in range(0,length,MIB):
            data=src.read(min(MIB,length-n))
            if len(data)!=min(MIB,length-n):raise OSError('Short boot backup read')
            out.write(data)
        out.flush();os.fsync(out.fileno())
    return {'file':destination.name,'bytes':length,'sha256':emmc.digest(destination)}


def verify_boot(flash,target,work,plan,expected=None):
    verify=work/'verify-boot';verify.mkdir()
    wanted=work/'expected-boot'
    if expected is None and not wanted.exists():wanted.mkdir();boot_tree(flash,wanted,plan)
    run('mount','-o','ro',str(target)+'p1',verify)
    try:clean.check_inventory(verify,clean.inventory(wanted) if expected is None else expected)
    finally:run('umount',verify)


def install_internal(source,target,flash,work,source_plan,expected,consent,test=False,stop=None,progress=None,finalize=None,installation=None):
    progress=progress or (lambda text,percent:None)
    clean.guard_source(source,flash,source_plan,test,allow_small=True)
    target_guard(source,target,expected,test)
    if source_plan.get('sd_test'):raise ValueError('This SD-only image cannot install internal storage')
    if source_plan.get('module_catalog_sha256') and (finalize is None or installation is None):
        raise ValueError('Module installation requires a bound feature selection and publisher')
    if consent!=confirmation(expected):raise ValueError('Internal erase confirmation is required')
    binary=loader(flash) # Verify before any target write, including GPT.
    source_files=clean.inventory(flash)
    # The source remains small and independently bootable as the recovery card.
    seed=work/'sd-state';seed.mkdir()
    run('mount',str(source)+'p2',seed)
    journal=seed/JOURNAL;journal.mkdir(mode=0o700,exist_ok=True);journal.chmod(0o700)
    lock=(journal/'install.lock').open('a')
    state_file=journal/'state.json';state=None
    mounted=[]
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if state_file.exists():
            state=json.loads(state_file.read_text())
            if (state.get('source')!=source_plan or state.get('target')!=expected
                    or state.get('source_files')!=source_files or state.get('installation')!=installation):raise ValueError('Saved installation belongs to different media or firmware')
            clean.check_plan(state['plan'])
        else:
            progress('Saving internal boot recovery data',5)
            # Stale partial backups from a failure before the journal are not a
            # complete recovery set. Stop instead of overwriting them.
            if any(p.name!='install.lock' for p in journal.iterdir()):
                raise ValueError('Incomplete backup exists; inspect the saved SD recovery data')
            backups=[backup_extent(target,journal/'internal-first16MiB.bin',0,16*MIB),
                     backup_extent(target,journal/'internal-last1MiB.bin',expected['bytes']-MIB,MIB)]
            if not test:
                for n in (0,1):
                    part=Path(str(target)+'boot'+str(n))
                    if part.exists():
                        length=int(run('blockdev','--getsize64',part))
                        backups.append(backup_extent(part,journal/('internal-boot'+str(n)+'.bin'),0,length))
            state={'schema':1,'phase':'prepared','source':source_plan,'target':expected,
                   'plan':new_plan(),'source_files':source_files,'backups':backups,'installation':installation}
            card.save(state_file,state)
        plan=state['plan'];desired=clean.final_geometry(plan,expected['bytes'])
        phases=('prepared','formatting','formatted','copying','verified','writing-loader','complete')
        if state['phase'] not in phases:raise ValueError('Unknown internal installation phase')
        for item in state['backups']:
            p=journal/item['file']
            if p.stat().st_size!=item['bytes'] or emmc.digest(p)!=item['sha256']:
                raise ValueError('Internal boot recovery backup changed')
        def save(phase):
            state['phase']=phase;state.pop('error',None);card.save(state_file,state)
        if state['phase']=='complete':
            check_table(target,plan,expected['bytes'])
            clean.filesystem(str(target)+'p1','vfat',plan['boot_uuid'])
            clean.filesystem(str(target)+'p2','ext4',plan['storage_uuid'])
            verify_boot(flash,target,work,plan,state.get('boot_inventory'))
            with target.open('rb') as raw:
                raw.seek(32768)
                if hashlib.sha256(raw.read(LOADER_BYTES)).hexdigest()!=LOADER_SHA:
                    raise ValueError('Completed installation bootloader changed')
            return state
        if state['phase'] in ('prepared','formatting'):
            target_guard(source,target,expected,test)
            if state['phase']=='prepared':
                # The on-screen selection/confirmation must still refer to the
                # internal contents whose boot area was just backed up.
                with target.open('rb') as stream:
                    if hashlib.sha256(stream.read(16*MIB)).hexdigest()!=state['backups'][0]['sha256']:
                        raise ValueError('Internal contents changed after backup')
            else:
                # Formatting may be retried after a power cut, but never across
                # another installation that replaced the raw boot chain.
                with target.open('rb') as a,(journal/state['backups'][0]['file']).open('rb') as b:
                    a.seek(32768);b.seek(32768)
                    if a.read(16*MIB-32768)!=b.read(16*MIB-32768):
                        raise ValueError('Internal boot area changed outside this installation')
            if not test:run('blockdev','--setrw',target)
            save('formatting');progress('Preparing internal storage',15)
            remove_mappings(target)
            fd=os.open(target,os.O_RDWR|os.O_CLOEXEC)
            try:
                for offset,data in emmc.gpt_regions(expected['bytes'],plan['disk_guid'],plan['partition_guids'],**plan['final']):
                    emmc.write_all(fd,data,offset);os.fsync(fd)
            finally:os.close(fd)
            for n,g in desired.items():card.kernel_partition(target,n,g)
            check_table(target,plan,expected['bytes'])
            run('mkfs.vfat','-F','32','-n','ROCKNIX','-i',plan['boot_uuid'].replace('-',''),str(target)+'p1')
            run('mkfs.ext4','-F','-q','-b','4096','-i','16384','-m','1','-L','STORAGE','-U',plan['storage_uuid'],str(target)+'p2')
            run('mkfs.exfat','-L','SLOT',str(target)+'p3');save('formatted')
        check_table(target,plan,expected['bytes'])
        clean.filesystem(str(target)+'p1','vfat',plan['boot_uuid'])
        clean.filesystem(str(target)+'p2','ext4',plan['storage_uuid'])
        if run('blkid','-p','-s','TYPE','-o','value',str(target)+'p3')!='exfat':raise ValueError('Internal content filesystem changed')
        if stop=='formatted':raise RuntimeError('Intentional test interruption after internal format')
        if state['phase'] in ('formatted','copying'):
            save('copying');progress('Installing Slot and the system',45)
            boot=work/'target-boot';storage=work/'target-state';content=work/'target-content'
            expected_boot=work/'expected-boot';expected_boot.mkdir(exist_ok=True)
            boot_tree(flash,expected_boot,plan)
            wanted=clean.inventory(expected_boot)
            for n,path in ((1,boot),(2,storage),(3,content)):
                path.mkdir();run('mount',str(target)+'p'+str(n),path);mounted.append(path)
            if finalize:
                # Compression can be interrupted before the copying phase is
                # committed. Only its journal-bound FAT output may be removed.
                clean.module('module_install_resume','slot-module-install.py').discard_pending(boot,state,source_plan)
            boot_tree(flash,boot,plan,durable=True,payload=source_files)
            for name in clean.CONTENT:(content/name).mkdir(parents=True,exist_ok=True)
            card.save(storage/'.slot-clean-layout.json',{'schema':1,'phase':'complete','plan':plan,
                      'partitions':{str(n):list(g) for n,g in desired.items()},'installed_from_sd':source_plan['disk_guid']})
            run('sync');progress('Checking the installation',75)
            clean.check_inventory(boot,wanted)
            if (storage/'slot-manager').exists():
                raise ValueError('Internal state is not a clean factory installation')
            if finalize:
                finalize(storage,boot,journal,state,seed)
                published=state.get('module_publication')
                if not published or emmc.digest(boot/'SYSTEM')!=published['sha256']:
                    raise ValueError('Internal module publication was not verified')
                actual=clean.inventory(boot)
                changed={n for n in actual.keys()|wanted.keys() if actual.get(n)!=wanted.get(n)}
                if not changed<={'SYSTEM','SYSTEM.md5'}:raise ValueError('Unexpected internal boot publication')
                wanted=actual
            state['boot_inventory']=wanted;card.save(state_file,state)
            for path in reversed(mounted):run('umount',path)
            mounted.clear();save('verified')
        if stop=='verified':raise RuntimeError('Intentional test interruption before bootloader write')
        # A resumed verified/loader stage must still match the payload that the
        # user selected; filesystem UUIDs alone cannot prove the boot files.
        verify_boot(flash,target,work,plan,state.get('boot_inventory'))
        target_guard(source,target,expected,test);progress('Installing the recovery bootloader',90)
        save('writing-loader')
        fd=os.open(target,os.O_RDWR|os.O_CLOEXEC)
        try:
            emmc.write_all(fd,binary.read_bytes(),32768);os.fsync(fd)
            if hashlib.sha256(os.pread(fd,LOADER_BYTES,32768)).hexdigest()!=LOADER_SHA:
                raise ValueError('Internal bootloader readback did not match')
        finally:os.close(fd)
        save('complete');progress('Ready to restart',100)
        return state
    except Exception as error:
        if state is not None:
            state['error']=str(error);card.save(state_file,state)
        raise
    finally:
        try:
            for path in reversed(mounted):run('umount',path)
        finally:
            lock.close();run('umount',seed)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();source=args.source
    flash=Path('/flash');plan=json.loads((flash/clean.MARKER).read_text())
    clean.guard_source(source,flash,plan,allow_small=True)
    info=identity(source)
    info['layout']=dict(plan['final'])
    if info['content_bytes'] is not None:info['content_bytes']=clean.final_geometry(plan,info['bytes'])[3][1]
    if info['type']!='SD':raise ValueError('Start the setup image from TF1')
    target=None if plan.get('sd_test') else discover_target(source)
    modules=None;module_install=None;setup_host=None;debug_child=None
    if plan.get('module_catalog_sha256'):
        module_install=clean.module('module_install','slot-module-install.py')
        seed=Path('/run/slot-module-preview');seed.mkdir()
        run('mount','-o','ro',str(source)+'p2',seed)
        try:
            modules=module_install.catalog(seed,plan)
            if plan.get('setup_debug'):
                if not plan.get('private_host_sha256'):raise ValueError('Setup debugging requires a pinned private test host key')
                host=seed/'.slot-modules/private/ssh_host_ed25519_key'
                if module_install.m.digest(host)!=plan['private_host_sha256']:raise ValueError('Setup host identity changed')
                setup_host=Path('/run/slot-setup-host-key');setup_host.write_bytes(host.read_bytes());setup_host.chmod(0o600)
        finally:run('umount',seed);seed.rmdir()
    # The kernel joypad module is the only extra hardware needed by this RAM UI.
    subprocess.run(['modprobe','-d','/usr/lib/kernel-overlays/base','rocknix_singleadc_joypad'],check=True)
    ui_spec=importlib.util.spec_from_file_location('setup_ui',HERE/'slot-setup-ui.py')
    ui=importlib.util.module_from_spec(ui_spec);ui_spec.loader.exec_module(ui)
    debug_spec=importlib.util.spec_from_file_location('setup_debug',HERE/'slot-setup-debug.py')
    debug=importlib.util.module_from_spec(debug_spec);debug_spec.loader.exec_module(debug)
    profile=debug.load(HERE/debug.PROFILE)
    if plan.get('setup_debug'):
        if profile is None or setup_host is None:raise ValueError('Private setup debugging data is unavailable')
        debug_child=subprocess.Popen([os.sys.executable,str(HERE/'slot-setup-access.py'),
                    '--profile',str(HERE/debug.PROFILE),'--host-key',str(setup_host),
                    '--host-sha256',plan['private_host_sha256']],
                    stdout=open('/run/slot-setup-access.log','w'),stderr=subprocess.STDOUT)
    screen=ui.Screen(HERE/'slot-setup-font.json.gz',info,target,profile,modules,sd_test=plan.get('sd_test') is True)
    action='stopped'
    try:
        while True:
            action=screen.choose()
            if action in ('reboot','poweroff'):return
            work=Path('/run')/('slot-setup-'+uuid.uuid4().hex);work.mkdir(mode=0o700)
            try:
                if plan.get('sd_test') and action!='sd':raise ValueError('This test image cannot write internal storage')
                finish=None
                if modules:
                    chosen=module_install.m.selection(modules,screen.model.features)
                    finish=lambda storage,boot,journal,state:module_install.finalize(
                        storage,boot,journal,state,plan,chosen,debug,profile,screen.model.options,screen.progress)
                if action=='sd':clean.setup(source,flash,work,plan,progress=screen.progress,finalize=finish)
                else:
                    internal_finish=None;installation=None
                    if modules:
                        internal_finish=lambda storage,boot,journal,state,seed:module_install.finalize(
                            storage,boot,journal,state,plan,chosen,debug,profile,screen.model.options,screen.progress,seed=seed)
                        installation={'catalog':plan['module_catalog_sha256'],'selected':chosen,'options':screen.model.options}
                    install_internal(source,Path(target['device']),flash,work,plan,target,
                                     confirmation(target),progress=screen.progress,finalize=internal_finish,installation=installation)
                if not modules and profile and any(screen.model.options.values()):
                    destination=source if action=='sd' else Path(target['device'])
                    state_root=work/'debug-state';state_root.mkdir()
                    # Re-check source/target identity before the only optional
                    # write. Installation has already verified its partition map.
                    if action=='emmc':target_guard(source,destination,target)
                    run('mount',str(destination)+'p2',state_root)
                    try:debug.provision(state_root,profile,screen.model.options)
                    finally:run('umount',state_root)
                screen.done()
            except Exception as error:screen.error(str(error))
            finally:
                # Never recursively remove a still-mounted destination after a
                # failed unmount. Ordinary retries should release their RAM files.
                mounts=[line.split(' - ',1)[0].split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()]
                if not any(p==str(work) or p.startswith(str(work)+'/') for p in mounts):
                    shutil.rmtree(work)
    finally:
        if debug_child:
            debug_child.terminate()
            try:debug_child.wait(timeout=45)
            except subprocess.TimeoutExpired:debug_child.kill();debug_child.wait(timeout=5)
        screen.close()
        # The shell continuation reads this only after an explicit UI action.
        Path('/run/slot-setup-action').write_text(action if action in ('reboot','poweroff') else 'stopped')


if __name__=='__main__':main()
