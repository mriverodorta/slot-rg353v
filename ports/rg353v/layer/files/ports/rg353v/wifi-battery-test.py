#!/usr/bin/env python3
"""Detached, on-demand Wi-Fi battery A/B test with local and boot recovery."""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time

BASE = Path('/storage/.cache/slot-wifi-battery')
ACTIVE = BASE / 'active.json'
UNITS = Path('/storage/.config/system.d')
RUN_UNITS = Path('/run/systemd/system')
RECOVERY = 'slot-wifi-battery-restore.service'
DEADLINE = 'slot-wifi-battery-deadline.timer'
WORKER = 'slot-wifi-battery-test.service'
PUBLIC = Path('/storage/slotcontent/Diagnostics/Battery/WiFi')
UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_text_atomic(path, text, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as stream:
        os.chmod(tmp, mode)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    sync_directory(path.parent)


def write_json(path, data):
    write_text_atomic(path, json.dumps(data, indent=2) + '\n', mode=0o600)


def read_json(path):
    return json.loads(Path(path).read_text())


def command(args, timeout=45, check=True):
    # nmcli output can contain network names; never include it in exceptions/logs.
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(str(args[0]) + ' failed (exit ' + str(result.returncode) + ')')
    return result.stdout.strip()


def profiler():
    path = Path(__file__).with_name('battery-profiler.py')
    spec = importlib.util.spec_from_file_location('slot_battery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def board_check():
    if os.geteuid() != 0 or sys.platform != 'linux':
        raise ValueError('Run as root on the RG353V')
    compatible = Path('/sys/firmware/devicetree/base/compatible').read_bytes()
    if b'anbernic,rg353v' not in compatible:
        raise ValueError('This runner is specific to RG353V')


def job_path(value):
    path = Path(value).resolve()
    if path.parent != BASE.resolve() or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', path.name):
        raise ValueError('Job must be a direct child of the private test directory')
    return path


def wifi_uuid():
    value = command(['nmcli', '-g', 'GENERAL.CON-UUID', 'device', 'show', 'wlan0'])
    return value if UUID.fullmatch(value) else None


def radio():
    return command(['nmcli', 'radio', 'wifi'])


def validate_options(args):
    if args.mode not in ('shelf', 'gameplay'):
        raise ValueError('Only awake shelf/gameplay tests are supported')
    if args.smoke:
        return {'duration': 30, 'warmup': 0, 'settle': 3, 'min_start': 20,
                'mode': args.mode, 'workload': args.workload, 'smoke': True}
    if not 780 <= args.duration <= 1800:
        raise ValueError('Each measured phase must be 780–1800 seconds')
    return {'duration': args.duration, 'warmup': 120, 'settle': 30,
            'min_start': 35, 'mode': args.mode, 'workload': args.workload, 'smoke': False}


def eligible(sample, module, minimum):
    e = module.electrical(sample)
    if e['charger_online'] or e['status'] != 'Discharging':
        raise ValueError('Unplug the handheld; charging invalidates this test')
    if e['capacity_pct'] is None or e['capacity_pct'] < minimum:
        raise ValueError('Battery is below the required starting charge (' + str(minimum) + '%)')
    if Path('/run/slot-usb/active').exists():
        raise ValueError('Exit USB storage before testing')
    return e


def arm_recovery(job, seconds):
    script = Path(__file__).resolve()
    if not re.fullmatch(r'[/A-Za-z0-9_.-]+', str(script)):
        raise ValueError('Install the runner at a path without whitespace')
    UNITS.mkdir(parents=True, exist_ok=True)
    unit = ('[Unit]\nDescription=Restore Wi-Fi after a local battery test\n'
            'Wants=NetworkManager.service\nAfter=NetworkManager.service\nStartLimitIntervalSec=0\n'
            '[Service]\nType=oneshot\nExecStart=/usr/bin/python3 ' + str(script) +
            ' restore --job ' + str(job) + ' --reason recovery-service\n'
            'Restart=on-failure\nRestartSec=30\nTimeoutStartSec=90\n'
            '[Install]\nWantedBy=multi-user.target\n')
    if (UNITS / RECOVERY).exists():
        raise ValueError('A recovery unit already exists; restore its experiment first')
    write_text_atomic(UNITS / RECOVERY, unit)
    wants = UNITS / 'multi-user.target.wants'
    wants.mkdir(exist_ok=True)
    (wants / RECOVERY).symlink_to(UNITS / RECOVERY)
    sync_directory(wants)
    write_text_atomic(RUN_UNITS / DEADLINE, '[Unit]\nDescription=Bound Wi-Fi battery experiment\n'
                                    '[Timer]\nOnActiveSec=' + str(seconds) +
                                    '\nAccuracySec=1s\nUnit=' + RECOVERY + '\n')
    command(['systemctl', 'daemon-reload'])
    command(['systemctl', 'start', DEADLINE])
    assert command(['systemctl', 'is-active', DEADLINE]) == 'active'


def disarm_recovery(job):
    # Only remove recovery units belonging to this job, never a newer run.
    recovery = UNITS / RECOVERY
    if recovery.exists() and ('--job ' + str(job) + ' ') not in recovery.read_text():
        raise ValueError('Recovery unit belongs to another experiment')
    if ACTIVE.exists() and read_json(ACTIVE)['job'] != str(job):
        raise ValueError('Another experiment owns recovery')
    command(['systemctl', 'stop', DEADLINE], check=False)
    for p in (RUN_UNITS / DEADLINE, UNITS / 'multi-user.target.wants' / RECOVERY, UNITS / RECOVERY):
        p.unlink(missing_ok=True)
    if ACTIVE.exists() and read_json(ACTIVE)['job'] == str(job):
        ACTIVE.unlink()
    command(['systemctl', 'daemon-reload'])


def restore(job, reason):
    job = job_path(job)
    with (job / 'restore.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_json(job / 'state.json')
        if state.get('restored'):
            if ACTIVE.exists() and read_json(ACTIVE)['job'] == str(job):
                disarm_recovery(job)
            return True
        if not UUID.fullmatch(state['connection_uuid']):
            raise ValueError('Invalid saved connection identifier')
        # A stale callback must never alter the radio for a newer test.
        if not ACTIVE.exists() or read_json(ACTIVE)['job'] != str(job):
            raise ValueError('Recovery ownership does not match')
        try:
            command(['nmcli', 'radio', 'wifi', 'on'])
            if wifi_uuid() != state['connection_uuid']:
                command(['nmcli', '--wait', '25', 'connection', 'up', 'uuid',
                         state['connection_uuid'], 'ifname', 'wlan0'], timeout=35)
            if radio() != 'enabled' or wifi_uuid() != state['connection_uuid']:
                raise RuntimeError('Original Wi-Fi connection has not returned')
            state.update(restored=True, restored_reason=reason, restored_at=time.time())
            write_json(job / 'state.json', state)
            write_json(job / 'recovery.json', {'restored': True, 'reason': reason,
                                              'original_connection_verified': True})
            disarm_recovery(job)
            return True
        except Exception:
            write_json(job / 'recovery.json', {'restored': False, 'reason': reason,
                                              'retry_service_retained': True})
            # The durable service retries every 30 seconds and also runs on reboot.
            command(['systemctl', 'start', '--no-block', RECOVERY], check=False)
            raise


def disable_wifi(job):
    # Serialize radio-off with recovery: a deadline can fire between phases.
    with (job / 'restore.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if read_json(job / 'state.json').get('restored'):
            raise RuntimeError('Recovery already ended the experiment')
        if not ACTIVE.exists() or read_json(ACTIVE)['job'] != str(job):
            raise RuntimeError('Experiment ownership changed')
        command(['nmcli', 'radio', 'wifi', 'off'])
        if radio() != 'disabled':
            raise RuntimeError('Wi-Fi could not be disabled')


def status(job, phase, **extra):
    write_json(job / 'status.json', {'phase': phase, 'updated_at': time.time(), **extra})


def guard(job, state, module):
    if read_json(job / 'state.json').get('restored'):
        raise RuntimeError('Recovery ended the experiment')
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != state['boot_id']:
        raise RuntimeError('Boot changed')
    sample = module.Collector().sample()
    eligible(sample, module, 16)
    pending = module.safe_json(module.read('/storage/slot-manager/state.json')).get('pending')
    if pending:
        raise RuntimeError('An update trial started during the experiment')
    if sample['settings'] != state['settings']:
        raise RuntimeError('Workload/settings changed; comparison stopped')
    for key in ('governors', 'frequency_limits', 'boost', 'cpu_governor_tunables', 'gpu_policy', 'mem_sleep'):
        if sample[key] != state['policies'][key]:
            raise RuntimeError('Operating policy changed; comparison stopped')


def phase(job, state, name, module):
    opts = state['options']
    guard(job, state, module)
    expected = 'enabled' if name == 'wifi-on' else 'disabled'
    if radio() != expected:
        raise RuntimeError('Wi-Fi radio state does not match phase')
    if name == 'wifi-on' and wifi_uuid() != state['connection_uuid']:
        raise RuntimeError('Original connection is not active')
    status(job, name, requested_duration_s=opts['duration'])
    args = ['/usr/bin/python3', str(Path(__file__).with_name('battery-profiler.py')),
            'record', '--mode', opts['mode'], '--workload', opts['workload'],
            '--duration', str(opts['duration']), '--interval', '15', '--warmup',
            str(opts['warmup']), '--output', str(job / name)]
    child = None
    try:
        with (job / (name + '.stdout')).open('w') as out, (job / (name + '.stderr')).open('w') as err:
            child = subprocess.Popen(args, stdout=out, stderr=err)
            started = time.monotonic()
            while child.poll() is None:
                time.sleep(5)
                guard(job, state, module)
                if time.monotonic() - started > opts['duration'] + 30:
                    raise TimeoutError('Sampler exceeded phase deadline')
            if child.returncode:
                raise RuntimeError('Battery sampler failed')
        report = read_json(job / name / 'summary.json')
        if report['metadata']['stop_reason'] != 'duration':
            raise RuntimeError('Sampler ended early: ' + report['metadata']['stop_reason'])
        if not opts['smoke'] and not report['comparable_awake_run']:
            raise RuntimeError('Capture did not qualify; inspect its report')
        if radio() != expected:
            raise RuntimeError('Radio changed during phase')
        if name == 'wifi-on' and wifi_uuid() != state['connection_uuid']:
            raise RuntimeError('Original connection changed during phase')
        return report
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def worker(job):
    job = job_path(job)
    state = read_json(job / 'state.json')
    module = profiler()
    def stopped(*unused):
        raise InterruptedError('Worker interrupted')
    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGINT, stopped)
    try:
        opts = state['options']
        status(job, 'settling-wifi-on')
        time.sleep(opts['settle'])
        a = phase(job, state, 'wifi-on', module)
        guard(job, state, module)
        disable_wifi(job)
        status(job, 'settling-wifi-off')
        time.sleep(opts['settle'])
        b = phase(job, state, 'wifi-off', module)
        result = module.compare(a, b, vary_conditions=['wifi'])
        if opts['smoke']:
            result = {'smoke_test': True, 'both_phases_completed': True,
                      'comparable': False, 'power_reduction_pct': None,
                      'reason': 'Short recovery check; not a battery-life measurement'}
        write_json(job / 'comparison.json', result)
        status(job, 'complete', qualified=result['comparable'])
    except BaseException as exc:
        # Record type only; command output/SSID/passwords never enter reports.
        status(job, 'aborted', error_type=type(exc).__name__)
        raise
    finally:
        restore(job, 'worker-finally')
    export_results(job)


def export_results(job):
    # Only allowlisted reports leave the private job directory. Never export state.json.
    if Path('/run/slot-usb/active').exists():
        raise RuntimeError('USB storage owns content; leave reports in the private job directory')
    dest = PUBLIC / job.name
    dest.mkdir(parents=True, exist_ok=True)
    for name in ('comparison.json', 'status.json', 'recovery.json'):
        shutil.copy2(job / name, dest / name)
    for phase_name in ('wifi-on', 'wifi-off'):
        folder = dest / phase_name
        folder.mkdir(exist_ok=True)
        for name in ('samples.jsonl', 'samples.csv', 'summary.json', 'report.md'):
            source = job / phase_name / name
            if source.is_file():
                shutil.copy2(source, folder / name)
    result = read_json(job / 'comparison.json')
    if result.get('smoke_test'):
        text = ('# Wi-Fi recovery smoke test\n\nBoth short recording phases completed. '
                'This does not qualify as a battery comparison and makes no savings claim.\n')
    else:
        text = ('# Wi-Fi battery comparison\n\nSame awake workload with Wi-Fi connected, then radio disabled. '
                'See comparison.json and both raw captures for results and qualification. '
                'A sequential pair is not a full battery-runtime measurement; repeat matched runs. '
                'Game frame delivery and audio quality require separate verification.\n')
    text += '\nWi-Fi restoration to the original connection was verified. Private connection identifiers are excluded.\n'
    write_text_atomic(dest / 'README.md', text)


def start(args):
    opts = validate_options(args)
    board_check()
    BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (BASE / 'start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if ACTIVE.exists() or (UNITS / RECOVERY).exists() or (RUN_UNITS / DEADLINE).exists():
            raise ValueError('An experiment/recovery unit is pending; restore it before starting another')
        module = profiler()
        sample = module.Collector().sample()
        eligible(sample, module, opts['min_start'])
        if module.safe_json(module.read('/storage/slot-manager/state.json')).get('pending'):
            raise ValueError('Finish the pending update trial before testing')
        original_uuid = wifi_uuid()
        if radio() != 'enabled' or not original_uuid:
            raise ValueError('Start with Wi-Fi enabled and connected')
        if (opts['mode'] == 'shelf') != (not sample['settings'].get('cart')):
            raise ValueError('Mode does not match the current shelf/gameplay state')
        job = (BASE / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')).resolve()
        job.mkdir(mode=0o700)
        state = {'schema': 1, 'connection_uuid': original_uuid, 'boot_id': sample['boot_id'],
                 'settings': sample['settings'], 'options': opts, 'restored': False,
                 'policies': {k: sample[k] for k in ('governors', 'frequency_limits', 'boost',
                              'cpu_governor_tunables', 'gpu_policy', 'mem_sleep')}}
        write_json(job / 'state.json', state)
        write_json(ACTIVE, {'job': str(job)})
        bound = opts['duration'] * 2 + opts['settle'] * 2 + 180
        try:
            arm_recovery(job, bound)
            command(['systemd-run', '--collect', '--unit=' + WORKER,
                     '--property=Nice=19', '--property=IOSchedulingClass=idle',
                     '--property=RuntimeMaxSec=' + str(bound - 30),
                     '--property=TimeoutStopSec=60',
                     '--property=ExecStopPost=/usr/bin/python3 ' + str(Path(__file__).resolve()) +
                     ' restore --job ' + str(job) + ' --reason worker-exit',
                     '/usr/bin/python3', str(Path(__file__).resolve()), 'worker', '--job', str(job)])
        except BaseException:
            restore(job, 'start-failed')
            raise
    print(json.dumps({'job': str(job), 'detached': True, 'smoke_test': opts['smoke'],
                      'expected_recording_s': 2 * (opts['duration'] + opts['settle']),
                      'recovery_deadline_s': bound}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('start')
    p.add_argument('--mode', choices=('shelf', 'gameplay'), default='shelf')
    p.add_argument('--workload', default='Unchanged cartridge shelf')
    p.add_argument('--duration', type=int, default=780, help='Seconds per phase')
    p.add_argument('--smoke', action='store_true', help='Two 30-second recovery phases; never qualifies power savings')
    for name in ('worker', 'restore', 'status'):
        p = sub.add_parser(name)
        p.add_argument('--job', required=True)
        if name == 'restore':
            p.add_argument('--reason', default='manual')
    args = parser.parse_args()
    try:
        if args.command == 'start':
            start(args)
        else:
            board_check()
            job = job_path(args.job)
            if args.command == 'worker':
                worker(job)
            elif args.command == 'restore':
                restore(job, args.reason)
            else:
                print(json.dumps({'status': read_json(job / 'status.json'),
                                  'restored': read_json(job / 'state.json')['restored']}))
    except (OSError, ValueError, RuntimeError, TimeoutError, InterruptedError, subprocess.SubprocessError):
        parser.exit(1, 'Wi-Fi battery operation stopped; inspect private status/recovery files.\n')


if __name__ == '__main__':
    main()
