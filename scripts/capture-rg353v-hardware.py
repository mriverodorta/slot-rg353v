#!/usr/bin/env python3
"""Read-only release-candidate capture over SSH; never inject input or reboot.

The private JSON includes filenames, local network details and configuration
hashes. Review it before sharing. Run on the shelf for comparable manifests.
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess


PROBE = r'''
import datetime, glob, hashlib, json, os, platform, shlex, subprocess
from pathlib import Path

def read(path):
    try: return Path(path).read_text().replace('\0', '').strip()
    except (OSError, UnicodeError): return None

def command(args):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=15)
        return {'exit': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e: return {'error': str(e)}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

root = Path('/storage/slotcontent')
manager = json.loads(Path('/storage/slot-manager/state.json').read_text())
pids = []
for p in Path('/proc').iterdir():
    if p.name.isdigit():
        try:
            exe = (p/'exe').resolve(strict=True)
            if exe.name == 'slot': pids.append((p, exe))
        except OSError: pass
runtime = []
for p, exe in pids:
    files = {str(exe): digest(p/'exe')}
    for name in ['mgba_libretro.so', 'gpsp_libretro.so']:
        core = exe.parent/name
        if core.is_file(): files[str(core)] = digest(core)
    runtime.append({'pid': int(p.name), 'exe': str(exe), 'files': files,
                    'status': read(p/'status')})
files = {}
for folder in ['Games', 'Labels', 'Wallpapers', 'BIOS', 'Config', 'Saves', 'States']:
    for p in (root/folder).rglob('*'):
        if p.is_file() and not p.is_symlink():
            files[str(p.relative_to(root))] = {'bytes': p.stat().st_size, 'sha256': digest(p)}
cfg = read(root/'Config/slot.state') or ''
cart = next((l.partition('=')[2] for l in cfg.splitlines() if l.startswith('cart=')), None)
panels = {p: read(p) for p in glob.glob('/sys/firmware/devicetree/base/**/panel*/compatible', recursive=True)}
drm = {p: read(p) for p in glob.glob('/sys/class/drm/*/modes')}
battery = {p: read(p) for p in glob.glob('/sys/class/power_supply/*/*')
           if Path(p).name in ['status','online','capacity','charge_now','charge_full','current_avg','voltage_avg']}
services = {name: command(['systemctl','is-active',name]) for name in
            ['slot-rg353v','input','NetworkManager','sshd','samba']}
failed = command(['systemctl','--failed','--no-legend','--no-pager'])
wifi = command(['nmcli','-g','GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS','device','show','wlan0'])
startup = read(root/'Diagnostics/slot-startup.log') or ''
cmdline = read('/proc/cmdline') or ''
firmware = {}
for word in shlex.split(cmdline):
    name, _, value = word.partition('=')
    if name in ['BOOT_IMAGE', 'SYSTEM_IMAGE'] and value.startswith('/slot-os/'):
        path = Path('/flash') / value.lstrip('/')
        if '..' not in path.parts and path.is_file():
            firmware[name] = {'path': value, 'bytes': path.stat().st_size, 'sha256': digest(path)}
checks = {
    'one_slot_process': len(runtime) == 1,
    'component_confirmed': manager.get('pending') is None and bool(manager.get('current')),
    'slot_active': services['slot-rg353v'].get('stdout') == 'active',
    'legacy_input_inactive': services['input'].get('stdout') == 'inactive',
    'no_failed_units': failed.get('exit') == 0 and failed.get('stdout') == '',
    'wifi_connected': wifi.get('exit') == 0 and '100 (connected)' in wifi.get('stdout', ''),
    'first_frame_observed': 'slot: boot: first frame' in startup,
    'panel_640x480': any('640x480' in (v or '').splitlines() for v in drm.values()),
}
report = {
    'schema': 1, 'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'boot_id': read('/proc/sys/kernel/random/boot_id'), 'kernel': platform.release(),
    'model': read('/proc/device-tree/model'), 'cmdline': cmdline, 'firmware': firmware,
    'boot_config': read('/flash/extlinux/extlinux.conf'),
    'manager': manager, 'runtime': runtime, 'panel': panels, 'drm_modes': drm,
    'cart': cart, 'files': files, 'battery': battery,
    'partition': {p.name: {k: read(p/k) for k in ['start','size','partition']}
                  for p in Path('/sys/class/block').glob('mmcblk*p*') if (p/'partition').exists()},
    'services': services, 'failed': failed, 'wifi': wifi,
    'mem_sleep': read('/sys/power/mem_sleep'),
    'suspend': {p.name: read(p) for p in Path('/sys/power/suspend_stats').glob('*') if p.is_file()},
    'rtc_wakealarm': {p: read(p) for p in glob.glob('/sys/class/rtc/rtc*/wakealarm')},
    'audio': command(['amixer','-c','0','scontents']),
    'checks': checks,
}
print(json.dumps(report))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', help='root@handheld-IP')
    parser.add_argument('--key', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True,
                        help='New private JSON file; existing files are never overwritten')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.@:-]+', args.host) or args.host.startswith('-'):
        parser.error('Invalid SSH host')
    if args.output.exists():
        parser.error('Output already exists; use a new capture name')
    result = subprocess.run(
        ['ssh', '-i', str(args.key.expanduser()), '-o', 'IdentitiesOnly=yes',
         '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', args.host, 'python3 -'],
        input=PROBE, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise SystemExit('Capture failed: ' + result.stderr[-2000:])
    report = json.loads(result.stdout)
    report['capture_host_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    print(json.dumps({'output': str(args.output.resolve()), 'boot_id': report['boot_id'],
                      'revision': report['manager']['current'], 'cart': report['cart'],
                      'files': len(report['files']), 'panel': report['panel'],
                      'checks': report['checks']}, indent=2))
    if not all(report['checks'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
