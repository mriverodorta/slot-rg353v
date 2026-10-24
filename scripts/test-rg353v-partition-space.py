#!/usr/bin/env python3
"""Qualify actual module/OS payloads on owned 512 MiB Linux/FAT loop filesystems.

Opt in with SLOT_PARTITION_SPACE_TEST=1, as root inside a disposable Linux
container. This program never accepts a device path, contacts hardware, or uses
personal content. Inputs are a public module kit and qualified OS capsules.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
MIB=1024**2


def load(name,path):
    loader=importlib.machinery.SourceFileLoader(name,str(path))
    spec=importlib.util.spec_from_loader(name,loader)
    result=importlib.util.module_from_spec(spec);loader.exec_module(result);return result


def run(*args):
    return subprocess.check_output([str(a) for a in args],text=True).strip()


class Disk:
    def __init__(self,folder,name,kind):
        self.path=folder/(name+'.img');self.mount=folder/name
        self.mount.mkdir();self.kind=kind;self.loop=None
        with self.path.open('xb') as stream:stream.truncate(512*MIB)
    def __enter__(self):
        self.loop=run('losetup','--find','--show',self.path)
        assert self.loop.startswith('/dev/loop')
        backing=Path('/sys/class/block',Path(self.loop).name,'loop/backing_file').read_text().strip()
        assert Path(backing).resolve()==self.path.resolve()
        try:
            if self.kind=='ext4':run('mkfs.ext4','-F','-q','-b','4096','-m','1',self.loop)
            else:run('mkfs.vfat','-F','32',self.loop)
            run('mount',self.loop,self.mount)
        except BaseException:
            run('losetup','-d',self.loop);self.loop=None;raise
        return self.mount
    def __exit__(self,*exc):
        run('umount',self.mount)
        run('losetup','-d',self.loop)


def use(path):
    stat=os.statvfs(path)
    return (stat.f_blocks-stat.f_bfree)*stat.f_frsize


def capsule(path,dest):
    dest.mkdir(parents=True)
    with tarfile.open(path) as archive:
        meta=json.load(archive.extractfile('manifest.json'))
        for name,info in meta['files'].items():
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            p=dest/name;p.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile('payload/'+name) as src,p.open('xb') as out:shutil.copyfileobj(src,out)
            assert p.stat().st_size==info['size']
    return meta


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kit',type=Path,required=True)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--target',type=Path,required=True)
    p.add_argument('--delta',type=Path,required=True)
    p.add_argument('--installer-image',type=Path,required=True,help='Public starter .img: use its complete boot backup, including installer/loader files')
    p.add_argument('--baseline-system-output',action='store_true',help='Measure the previous ext4-output workspace for comparison only')
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    if os.geteuid()!=0 or os.environ.get('SLOT_PARTITION_SPACE_TEST')!='1':
        p.error('Requires explicit disposable Linux container opt-in; no physical-device mode exists')
    if (a.kit/'private').exists():p.error('Use a public module kit, without owner provisioning')
    if a.installer_image.is_symlink() or not a.installer_image.is_file():p.error('Installer input must be a regular image file, not a device')
    module=load('space_modules',ROOT/'ports/rg353v/image/slot-modules.py')
    layout=load('space_layout',ROOT/'scripts/rg353v-card-layout.py')
    osup=load('space_os',ROOT/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-os-update')
    results={'partition_mib':{'boot':512,'system':512},'presets':{},
             'output_filesystem':'system-baseline' if a.baseline_system_output else 'boot'}
    with tempfile.TemporaryDirectory(prefix='slot-space-') as temporary:
        temporary=Path(temporary)
        starter=temporary/'starter-boot';starter.mkdir()
        parts=layout.partitions(a.installer_image)
        if set(parts)!={1,2} or parts[1][0]!=16*MIB:p.error('Use a clean public starter image')
        mounted=temporary/'starter-mount';mounted.mkdir()
        with layout.mounted(a.installer_image,*parts[1],mounted):
            plan=json.loads((mounted/'slot-clean-firstboot.json').read_text())
            if (plan.get('setup_debug') or plan.get('private_host_sha256')
                    or (mounted/'slot-setup-debug.json').exists()):p.error('Use a public starter without private provisioning')
            assert plan['module_catalog_sha256']==module.digest(a.kit/'catalog.json')
            shutil.copytree(mounted,starter,dirs_exist_ok=True)
        results['complete_boot_backup_bytes']=sum(f.stat().st_size for f in starter.rglob('*') if f.is_file())
        with Disk(temporary,'storage','ext4') as store,Disk(temporary,'flash','fat') as flash:
            meta=capsule(a.base,flash/'slot-os/base')
            shutil.copytree(flash/'slot-os/base',flash/'slot-os/previous')
            (flash/'extlinux').mkdir()
            (flash/'extlinux/extlinux.conf').write_text('LABEL slot\n  LINUX /slot-os/base/KERNEL\n  FDTDIR /slot-os/base/device_trees\n  APPEND boot=LABEL=ROCKNIX disk=LABEL=STORAGE SYSTEM_IMAGE=/slot-os/base/SYSTEM quiet\n')
            catalog=module.load(a.kit)
            presets={'minimal':['emulator-mgba'],
                     'recommended':['emulator-mgba','usb-storage','external-sd','filters','overlays','rewind'],
                     'full':[m['id'] for m in catalog['modules']]}
            for name,selected in presets.items():
                seed=store/'.slot-modules';shutil.copytree(a.kit,seed)
                # Model the durable SD boot backup retained until publication.
                backup=store/'.slot-clean-install/boot';backup.parent.mkdir();shutil.copytree(starter,backup)
                peak=[use(store)];boot_peak=[use(flash)];minimum_free=[shutil.disk_usage(store).free];stop=threading.Event()
                def watch():
                    while not stop.wait(.02):
                        peak[0]=max(peak[0],use(store))
                        boot_peak[0]=max(boot_peak[0],use(flash))
                        minimum_free[0]=min(minimum_free[0],shutil.disk_usage(store).free)
                watcher=threading.Thread(target=watch);watcher.start()
                try:
                    output=(store/'selected.sfs') if a.baseline_system_output else (flash/'SYSTEM.modules-new')
                    work=store/'build'
                    def progress(text,percent):
                        if percent==96:assert not (work/'root').exists(),'Two unpacked trees would overlap'
                    result=module.compose(seed,selected,work,output,progress)
                    peak[0]=max(peak[0],use(store))
                    boot_peak[0]=max(boot_peak[0],use(flash))
                    assert not (work/'root').exists() and not (work/'verify').exists()
                    if not a.baseline_system_output:assert not (store/'selected.sfs').exists()
                    assert minimum_free[0]>=64*MIB,'Less than 64 MiB free during composition'
                    assert use(store)<448*MIB,'Less than 64 MiB headroom at settled publication'
                    results['presets'][name]={'peak_used_bytes':peak[0],'system_bytes':result['system_bytes'],
                                             'compressed_output_filesystem':results['output_filesystem'],'boot_peak_used_bytes':boot_peak[0],
                                             'minimum_free_bytes':minimum_free[0],
                                             'free_bytes_after_composition':shutil.disk_usage(store).free}
                    assert shutil.disk_usage(flash).free>=64*MIB
                finally:stop.set();watcher.join()
                for path in (seed,backup.parent,work):shutil.rmtree(path)
                output.unlink()
            # Allocate real blocks to cover existing runtime/component revisions.
            with (store/'runtime-allowance').open('xb') as stream:
                for _ in range(32):stream.write(bytes(MIB))
            for kind,package in [('delta',a.delta),('full',a.target)]:
                download=store/'download.tar.gz';shutil.copyfile(package,download)
                staging=store/'stage';staging.mkdir()
                with tarfile.open(a.delta) as archive:delta_meta=json.load(archive.extractfile('manifest.json'))
                manager=osup.OSManager(store/'os',flash,store/'manager',temporary/'unused-system',delta_meta['base_runtime'])
                verified=manager.verify_bundle(download,osup.u.sha(download),staging)
                for file,info in verified['files'].items():
                    assert osup.u.sha(staging/file)==info['sha256']
                required=sum(v['size'] for v in verified['files'].values())+osup.BOOT_RESERVE
                assert shutil.disk_usage(flash).free>=required
                shutil.copytree(staging,flash/'slot-os/candidate')
                # Reserve a new frontend snapshot while reconstructed OS is staged.
                with (store/'factory-allowance').open('xb') as stream:
                    for _ in range(24):stream.write(bytes(MIB))
                results[kind]={'download_bytes':download.stat().st_size,'system_used_bytes':use(store),
                               'boot_used_bytes_with_three_sets':use(flash),
                               'system_free_bytes':shutil.disk_usage(store).free,
                               'boot_free_bytes':shutil.disk_usage(flash).free,
                               'all_target_hashes_verified':True}
                assert shutil.disk_usage(store).free>=64*MIB and shutil.disk_usage(flash).free>=64*MIB
                shutil.rmtree(flash/'slot-os/candidate');shutil.rmtree(staging)
                download.unlink();(store/'factory-allowance').unlink()
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results),flush=True)


if __name__=='__main__':main()
