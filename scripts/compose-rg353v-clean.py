#!/usr/bin/env python3
"""Build a clean, small SD image; never open a physical card or private snapshot."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import shutil
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('layout', ROOT/'scripts/rg353v-card-layout.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
spec = importlib.util.spec_from_file_location('clean_seed', ROOT/'ports/rg353v/image/slot-clean-firstboot.py')
clean = importlib.util.module_from_spec(spec); spec.loader.exec_module(clean)
MIB = clean.MIB

# These hooks are read by the existing initramfs. They exist only in the clean
# factory image and are removed before the first normal startup.
POST_FLASH = '''#!/bin/sh
if [ -f /flash/slot-clean-firstboot.json ]; then
  SYSTEM_TORAM=yes
fi
'''
POST_SYSROOT = '''#!/bin/sh
if [ -f /flash/slot-clean-firstboot.json ]; then
  slot_clean_fail() { echo "Clean setup stopped: $1" >&2; while :; do sleep 60; done; }
  mkdir -p /run/slot-clean-tools || slot_clean_fail "RAM directory unavailable"
  cp /flash/slot-clean-firstboot.py /flash/slot-card-firstboot.py /flash/slot-emmc-install.py /flash/slot-clean-run.sh /flash/slot-setup.py /flash/slot-setup-ui.py /flash/slot-setup-debug.py /flash/slot-setup-font.json.gz /run/slot-clean-tools/ || slot_clean_fail "RAM copy failed"
  if [ -f /flash/slot-setup-debug.json ]; then cp /flash/slot-setup-debug.json /run/slot-clean-tools/ || slot_clean_fail "Developer profile copy failed"; chmod 600 /run/slot-clean-tools/slot-setup-debug.json; fi
  cd / || slot_clean_fail "Cannot release working directory"
  # Exec closes the sourced FAT hook descriptor before the FAT is unmounted.
  exec /usr/bin/busybox sh /run/slot-clean-tools/slot-clean-run.sh
  slot_clean_fail "RAM handoff failed"
fi
'''
RAM_RUN = '''#!/bin/sh
fail() {
  slot_clean_reason=$1
  /usr/bin/slot-splash --error || :
  echo "Slot SD setup stopped: $slot_clean_reason" >/dev/tty0
  for slot_clean_boot in /sysroot/flash /flash; do
    [ -f "$slot_clean_boot/slot-clean-firstboot.json" ] || continue
    slot_clean_part=$(awk -v target="$slot_clean_boot" '$2 == target {print $1}' /proc/mounts)
    case "$slot_clean_part" in /dev/mmcblk*p1) slot_clean_parent=${slot_clean_part%p1};; *) continue;; esac
    [ "$(cat /sys/class/block/${slot_clean_parent##*/}/device/type)" = SD ] || continue
    mount -o remount,rw "$slot_clean_boot" || continue
    { echo "$slot_clean_reason"; cat /run/slot-clean-firstboot.log 2>/dev/null; } > "$slot_clean_boot/slot-setup-failure.log"
    sync
    mount -o remount,ro "$slot_clean_boot" || :
  done
  while :; do sleep 60; done
}
slot_clean_disk=$(awk '$2 == "/flash" {print $1}' /proc/mounts)
case "$slot_clean_disk" in /dev/mmcblk*p1) slot_clean_disk=${slot_clean_disk%p1};; *) fail "Unexpected boot disk";; esac
for slot_clean_mount in dev proc sys run; do
  mount --bind /$slot_clean_mount /sysroot/$slot_clean_mount || fail "RAM setup failed"
done
mount --move /flash /sysroot/flash || fail "Boot mount move failed"
chroot /sysroot /usr/bin/env PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C LANG=C PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 /run/slot-clean-tools/slot-setup.py --source "$slot_clean_disk" > /run/slot-clean-firstboot.log 2>&1 || fail "See /run/slot-clean-firstboot.log"
sync
case "$(cat /run/slot-setup-action)" in
  reboot) reboot -f;;
  poweroff) poweroff -f;;
  *) fail "Setup did not request a restart";;
esac
fail "Setup completed; restart required"
'''


def validate_factory_boot(tree):
    expected = {'KERNEL', 'SYSTEM', 'KERNEL.md5', 'SYSTEM.md5',
                'device_trees', 'overlays', 'extlinux'}
    if {p.name for p in tree.iterdir()} != expected:
        raise ValueError('Expected the factory boot tree; private/extra files are not publishable')
    if {p.name for p in (tree/'extlinux').iterdir()} != {'extlinux.conf'}:
        raise ValueError('Unexpected factory boot configuration or backup')


def compose(source, output, loader_file, debug_profile=None, module_kit=None, sd_test_guard=None, host_key=None, setup_debug=False, public=False):
    if public and (debug_profile or host_key or setup_debug):raise ValueError('Public images cannot contain private provisioning')
    if public and module_kit and (module_kit/'private').exists():raise ValueError('Private module data is not distributable')
    if setup_debug and not (module_kit and host_key and debug_profile):raise ValueError('Setup debugging requires a private module kit, profile and pinned host identity')
    if host_key and not (module_kit and debug_profile):raise ValueError('A seeded host identity is private-test-only')
    debug=None
    if debug_profile is not None:
        debug=clean.module("setup_debug", "slot-setup-debug.py").load(debug_profile)
        if debug is None:raise ValueError("Developer profile does not exist")
    if not source.is_file() or not source.name.endswith('.img') or output.exists():
        raise ValueError('Use a regular upstream .img and a fresh output file')
    parts = m.partitions(source)
    if set(parts) != {1, 2} or parts[1][0] != 16*MIB:
        raise ValueError('Unexpected upstream factory layout')
    policy=json.loads((ROOT/'ports/rg353v/image/installer-loader.json').read_text())
    if (not loader_file.is_file() or loader_file.stat().st_size!=policy['bytes']
            or hashlib.sha256(loader_file.read_bytes()).hexdigest()!=policy['sha256']):
        raise ValueError('Supply the pinned, validated RG353V eMMC/F-recovery loader')
    geometry = clean.initial_geometry()
    total = clean.STARTER_MIB*MIB
    boot_id = secrets.token_hex(4).upper()
    plan = {'schema': clean.PLAN_SCHEMA, 'kind': 'slot-clean-firstboot',
            'initial': dict(clean.INITIAL),
            'final': dict(clean.FINAL),
            'disk_guid': str(uuid.uuid4()), 'boot_uuid': boot_id[:4]+'-'+boot_id[4:],
            'storage_uuid': str(uuid.uuid4()),
            'partition_guids': {str(n): str(uuid.uuid4()) for n in (1, 2, 3)}}
    with tempfile.TemporaryDirectory(dir=output.parent) as name:
        temp = Path(name); mounted = temp/'mounted'; mounted.mkdir()
        boot = temp/'boot'; store = temp/'storage'; store.mkdir()
        # Read only the factory boot tree. Never take settings from a live device.
        with m.mounted(source, *parts[1], mounted):
            if any(p.is_symlink() for p in mounted.rglob('*')):
                raise ValueError('Unsupported upstream boot symlink')
            validate_factory_boot(mounted)
            shutil.copytree(mounted, boot)
        for filename in ('post-flash.sh', 'post-sysroot.sh', 'mount-storage.sh'):
            if (boot/filename).exists():
                raise ValueError('Unexpected upstream customization hook')
        for filename in ('KERNEL', 'SYSTEM', 'device_trees/rk3566-anbernic-rg353v.dtb'):
            if not (boot/filename).is_file():
                raise ValueError('Missing RG353V factory payload: '+filename)
        # The distribution target is this specific board, with fresh UUIDs.
        (boot/'extlinux/extlinux.conf').write_text(
            'LABEL Slot\n  LINUX /KERNEL\n  FDT /device_trees/rk3566-anbernic-rg353v.dtb\n'
            f'  APPEND boot=UUID={plan["boot_uuid"]} disk=UUID={plan["storage_uuid"]}'
            ' quiet console=ttyS2,1500000\n')
        if sd_test_guard:
            if not sd_test_guard.is_file():raise ValueError('Missing SD protection guard')
            shutil.copyfile(sd_test_guard,boot/'slot-sd-test-guard')
            (boot/'slot-sd-test-guard').chmod(0o755)
            plan.update(sd_test=True,setup_debug=setup_debug,sd_guard_sha256=hashlib.sha256(sd_test_guard.read_bytes()).hexdigest())
        if module_kit:
            engine=clean.module('module_engine','slot-modules.py')
            engine.load(module_kit)
            plan['setup_debug']=setup_debug
            plan['module_catalog_sha256']=engine.digest(module_kit/'catalog.json')
            shutil.copytree(module_kit,store/'.slot-modules')
            if host_key:
                # A new server identity for this private test card; never the
                # client's private key or the existing eMMC host identity.
                pub=subprocess.check_output(['ssh-keygen','-y','-f',str(host_key)],text=True).strip()
                if not pub.startswith('ssh-ed25519 '):raise ValueError('Expected a fresh Ed25519 test host key')
                private=store/'.slot-modules/private';private.mkdir(mode=0o700)
                shutil.copyfile(host_key,private/'ssh_host_ed25519_key');(private/'ssh_host_ed25519_key').chmod(0o600)
                (private/'ssh_host_ed25519_key.pub').write_text(pub+'\n')
                plan['private_host_sha256']=hashlib.sha256(host_key.read_bytes()).hexdigest()
        guard='/flash/slot-sd-test-guard >/dev/null || { echo "SD test protection failed" >&2; while :; do sleep 60; done; }\n' if sd_test_guard else ''
        (boot/'post-flash.sh').write_text('#!/bin/sh\n'+guard+POST_FLASH.split('\n',1)[1])
        (boot/'post-sysroot.sh').write_text(POST_SYSROOT.replace('/flash/slot-setup-debug.py ', '/flash/slot-setup-debug.py /flash/slot-modules.py /flash/slot-module-install.py /flash/slot-setup-access.py '))
        (boot/'slot-clean-run.sh').write_text(RAM_RUN)
        (boot/'slot-clean-firstboot.json').write_text(json.dumps(plan, indent=2)+'\n')
        for filename in ('slot-clean-firstboot.py', 'slot-card-firstboot.py', 'slot-emmc-install.py',
                         'slot-setup.py','slot-setup-ui.py','slot-setup-debug.py','slot-modules.py','slot-module-install.py','slot-setup-access.py','slot-setup-font.json.gz'):
            shutil.copyfile(ROOT/'ports/rg353v/image'/filename, boot/filename)
        (boot/'slot-setup-font.LICENSE.txt').write_text(
            (ROOT/'ports/rg353v/image/assets/label.ttf.OFL.txt').read_text()+'\n\n'+
            (ROOT/'ports/rg353v/image/assets/setup-menu-icons.ttf.LICENSE.txt').read_text())
        shutil.copyfile(loader_file,boot/'slot-installer-loader.bin')
        (boot/'slot-installer-loader.json').write_text(json.dumps(policy,indent=2)+'\n')
        if debug is not None:
            (boot/'slot-setup-debug.json').write_text(json.dumps(debug)+'\n')
            (boot/'slot-setup-debug.json').chmod(0o600)
        boot_payload = sum(p.stat().st_size for p in boot.rglob('*') if p.is_file())
        if boot_payload > clean.BOOT_PAYLOAD_LIMIT:
            raise ValueError('Clean boot payload has outgrown the reviewed starter layout')
        boot_fs = temp/'boot.fat'; store_fs = temp/'storage.ext4'
        for path, size in ((boot_fs, geometry[1][1]), (store_fs, geometry[2][1])):
            with path.open('xb') as stream:
                stream.truncate(size)
        m.run('mkfs.vfat', '-F', '32', '-n', 'ROCKNIX', '-i', boot_id, boot_fs)
        for entry in boot.iterdir():
            m.run('mcopy', '-s', '-i', boot_fs, entry, '::/')
        # Completely fresh writable state: no keys, passwords, games or history.
        m.run('mkfs.ext4', '-F', '-q', '-b', '4096', '-i', '16384', '-m', '1', '-L', 'STORAGE',
              '-U', plan['storage_uuid'], '-d', store, store_fs)
        with output.open('xb') as stream:
            stream.truncate(total)
        m.sparse_copy(source, output, limit=16*MIB)
        m.run('sgdisk', '--clear', '--disk-guid='+plan['disk_guid'], output)
        for n, (start, size) in geometry.items():
            m.run('sgdisk', f'--new={n}:{start//512}:{(start+size)//512-1}',
                  '--partition-guid='+str(n)+':'+plan['partition_guids'][str(n)],
                  '--typecode='+str(n)+':'+('0700' if n==1 else '8300'),
                  '--change-name='+str(n)+':'+('ROCKNIX' if n==1 else 'STORAGE'), output)
        m.run('sgdisk', '--attributes=1:set:2', output)
        m.sparse_copy(boot_fs, output, geometry[1][0])
        m.sparse_copy(store_fs, output, geometry[2][0])
        m.run('sgdisk', '--verify', output)
        if m.partitions(output) != geometry:
            raise ValueError('Clean starter partition bounds differ')
        report = {'schema': 1, 'clean': debug is None and host_key is None, 'private_test':debug is not None or host_key is not None, 'image_bytes': total,
                  'boot_payload_bytes': boot_payload, 'private_provisioning': debug is not None,
                  'starter_partitions': {str(n): list(g) for n,g in geometry.items()},
                  'first_boot_plan': plan, 'hardware_validated': False}
        report.update(setup_destinations=['sd'] if sd_test_guard else ['sd','emmc'],content_allocation='remaining aligned device capacity',
                      internal_loader_sha256=policy['sha256'])
        output.with_suffix('.layout.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--loader', type=Path, required=True)
    p.add_argument('--debug-profile',type=Path,help='Private test image only; contains saved Wi-Fi credentials')
    p.add_argument('--module-kit',type=Path)
    p.add_argument('--sd-test-guard',type=Path)
    p.add_argument('--host-key',type=Path,help='Fresh server identity for a private SD test only')
    p.add_argument('--setup-debug',action='store_true',help='Private RAM-only Wi-Fi/USB SSH during setup')
    p.add_argument('--public',action='store_true',help='Refuse all private provisioning in a distributable image')
    a = p.parse_args()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    compose(a.input, a.output, a.loader, a.debug_profile,a.module_kit,a.sd_test_guard,a.host_key,a.setup_debug,a.public)


if __name__ == '__main__':
    main()
