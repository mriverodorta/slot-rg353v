#!/usr/bin/env python3
"""Read-only on-device battery/CPU sampling; emit JSON lines to stdout.

Run through SSH with python3 -u - SECONDS INTERVAL < this-file.
Keep charging, brightness, workload and Wi-Fi matched between captures.
PMIC averages are estimates; no external power-meter accuracy is implied.
"""
import glob
import json
import pathlib
import sys
import time


def read(path):
    try:
        return pathlib.Path(path).read_text().strip()
    except OSError:
        return None


def number(path):
    try:
        return int(read(path))
    except (TypeError, ValueError):
        return None


def sample():
    supplies = {}
    for path in glob.glob('/sys/class/power_supply/*'):
        supplies[pathlib.Path(path).name] = {
            k: read(path + '/' + k) for k in (
                'status', 'online', 'capacity', 'current_avg', 'voltage_avg',
                'charge_now', 'charge_full', 'charge_full_design')}
    sensors = {}
    for pattern in ('/sys/class/backlight/*/brightness',
                    '/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq',
                    '/sys/class/devfreq/*/cur_freq',
                    '/sys/class/thermal/thermal_zone*/temp'):
        sensors.update({p: number(p) for p in glob.glob(pattern)})
    cpu = list(map(int, pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    procs = (read('/sys/fs/cgroup/system.slice/slot-rg353v.service/cgroup.procs') or
             read('/sys/fs/cgroup/systemd/system.slice/slot-rg353v.service/cgroup.procs'))
    if not procs:
        procs = ' '.join(pathlib.Path(p).parent.name for p in glob.glob('/proc/[0-9]*/comm')
                         if read(p) == 'slot')
    tasks = {}
    for pid in procs.split():
        stat = read('/proc/' + pid + '/stat')
        if stat:
            fields = stat.rsplit(')', 1)[1].split()
            tasks[pid] = {'comm': read('/proc/' + pid + '/comm'),
                          'ticks': int(fields[11]) + int(fields[12])}
    return {'wall_s': time.time(), 'monotonic_s': time.monotonic(),
            'boottime_s': time.clock_gettime(time.CLOCK_BOOTTIME),
            'supplies': supplies, 'sensors': sensors, 'cpu': cpu, 'tasks': tasks}


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if not 5 <= interval <= 60 or not interval <= seconds <= 3600:
        raise SystemExit('Use duration interval..3600 and interval 5..60 seconds')
    print(json.dumps({'metadata': {'kernel': read('/proc/version'),
          'boot_id': read('/proc/sys/kernel/random/boot_id'),
          'mem_sleep': read('/sys/power/mem_sleep'),
          'units': 'power_supply: microvolts, microamps, microamp-hours; temperatures: millidegrees C',
          'duration_s': seconds, 'interval_s': interval}}), flush=True)
    start = time.monotonic()
    for n in range(seconds // interval + 1):
        time.sleep(max(0, start + n * interval - time.monotonic()))
        print(json.dumps(sample()), flush=True)


if __name__ == '__main__':
    main()
