#!/usr/bin/env python3
"""Selected module publication, committed by the clean-layout transaction."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('modules',HERE/'slot-modules.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

GUARD='''#!/bin/sh
/flash/slot-sd-test-guard >/dev/null || { echo "SD test protection failed" >&2; while :; do sleep 60; done; }
'''
PENDING=('SYSTEM.modules-new','SYSTEM.md5.modules-new','post-flash.sh.modules-new')

def staging_record(plan):
    return {'schema':1,'source':plan['disk_guid'],'catalog':plan['module_catalog_sha256']}

def discard_pending(flash,state,plan):
    """Discard only interrupted output owned by this bound install transaction."""
    paths=[Path(flash)/name for name in PENDING]
    present=[p for p in paths if p.exists() or p.is_symlink()]
    if not present:return
    if state.get('module_staging')!=staging_record(plan):raise ValueError('Unknown boot module staging files')
    # Validate the whole set before deleting any entry. Never follow a symlink.
    if any(p.is_symlink() or not p.is_file() for p in present):raise ValueError('Unsupported boot module staging entry')
    for p in present:p.unlink()
    m.syncdir(flash)

def catalog(seed,plan):
    kit=Path(seed)/'.slot-modules'
    if m.digest(kit/'catalog.json')!=plan['module_catalog_sha256']:raise ValueError('Feature catalog changed')
    return m.load(kit)

def finalize(storage,flash,journal,state,plan,chosen,debug,profile,options,progress,seed=None):
    # Destination identity, confirmation and partition checks belong to the
    # enclosing SD/eMMC transaction. A separate seed keeps recovery SD intact.
    storage,flash,journal=map(Path,(storage,flash,journal))
    seed=storage if seed is None else Path(seed)
    data=catalog(seed,plan);selected=m.selection(data,chosen)
    scratch=storage/'.slot-module-install'
    if scratch.exists():
        if scratch.is_symlink() or not (scratch/'owned.json').is_file():raise ValueError('Unknown module staging directory')
        if json.loads((scratch/'owned.json').read_text())!={'schema':1,'catalog':plan['module_catalog_sha256']}:raise ValueError('Module staging belongs to another image')
        shutil.rmtree(scratch)
    scratch.mkdir(mode=0o700);m.save(scratch/'owned.json',{'schema':1,'catalog':plan['module_catalog_sha256']})
    discard_pending(flash,state,plan)
    # Keep the original bootable SYSTEM until compression and independent
    # verification succeed. Output goes straight to FAT, never via ext4 storage.
    state['module_staging']=staging_record(plan);m.save(journal/'state.json',state)
    pending=flash/PENDING[0]
    result=m.compose(seed/'.slot-modules',selected,scratch/'build',pending,progress)
    if profile and any(options.values()):debug.provision(storage,profile,options)
    host=seed/'.slot-modules/private/ssh_host_ed25519_key'
    if 'ssh' in selected and options.get('ssh') and host.is_file():
        if m.digest(host)!=plan.get('private_host_sha256'):raise ValueError('Private test host identity changed')
        debug.atomic(storage/'.cache/ssh/ssh_host_ed25519_key',host.read_bytes())
        debug.atomic(storage/'.cache/ssh/ssh_host_ed25519_key.pub',host.with_suffix('.pub').read_bytes())
    if m.digest(pending)!=result['system_sha256']:raise ValueError('Published system verification failed')
    state['module_publication']={'sha256':result['system_sha256'],'bytes':result['system_bytes']}
    m.save(journal/'state.json',state)
    os.replace(pending,flash/'SYSTEM');m.syncdir(flash)
    # MD5 is an upstream boot convention, not the trust check (SHA-256 above).
    checksum=hashlib.md5((flash/'SYSTEM').read_bytes()).hexdigest()
    with (flash/'SYSTEM.md5.modules-new').open('w') as out:
        out.write(checksum+'  SYSTEM\n');out.flush();os.fsync(out.fileno())
    os.replace(flash/'SYSTEM.md5.modules-new',flash/'SYSTEM.md5');m.syncdir(flash)
    if plan.get('sd_test'):
        with (flash/'post-flash.sh.modules-new').open('w') as out:
            out.write(GUARD);out.flush();os.fsync(out.fileno())
        os.replace(flash/'post-flash.sh.modules-new',flash/'post-flash.sh');m.syncdir(flash)
    m.save(storage/'.slot-module-install-complete.json',{**result,'catalog_sha256':plan['module_catalog_sha256']})
    os.sync()
