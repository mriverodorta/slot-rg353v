#!/usr/bin/env python3
"""On-demand RG353V battery measurements. Reads hardware; never changes power policy."""
import argparse
import csv
import datetime
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import statistics
import subprocess
import sys
import time

SCHEMA = 3
MAX_BYTES = 64 * 1024 * 1024
MAX_PROCESSES = 256
SUPPLY_FIELDS = ('type', 'status', 'online', 'present', 'capacity', 'current_avg',
                 'current_now', 'voltage_avg', 'voltage_now', 'charge_now',
                 'charge_full', 'charge_full_design', 'temp')
SETTINGS = ('cart', 'cart_platform', 'brightness', 'volume', 'volume_hp', 'muted',
            'muted_hp', 'shader_gba', 'shader_gb', 'integer_scale', 'game_border',
            'perfect_overlay', 'rewind', 'runahead', 'ff_speed', 'ff_sound',
            'colour_correction', 'sleep_shutdown_minutes', 'perfect_shader_gba',
            'perfect_shader_gb', 'perfect_colour_correction', 'show_fps', 'blue_light',
            'enhanced_audio', 'schedutil_governor', 'shader_gbc', 'colour_correction_gb', 'colour_correction_gbc',
            'perfect_shader_gbc', 'perfect_colour_correction_gb', 'perfect_colour_correction_gbc')
POLICY_CONDITIONS = ('cpu_governor_tunables', 'gpu_policy', 'audio_route', 'audio_pcm')
VARY_CONDITIONS = ('cpu_governor_tunables', 'gpu_policy', 'wifi')
ONDEMAND_PARAMETERS = ('sampling_rate', 'sampling_down_factor', 'up_threshold',
                      'ignore_nice_load', 'io_is_busy', 'powersave_bias')


def read(path, limit=16384):
    try:
        with Path(path).open('r') as stream:
            return stream.read(limit).strip()
    except (OSError, UnicodeError):
        return None


def integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def settings(text):
    return {k: v for line in (text or '').splitlines() if '=' in line
            for k, v in [line.split('=', 1)] if k in SETTINGS}


def safe_json(text):
    try:
        value = json.loads(text or '')
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


class Collector:
    def __init__(self, root=Path('/')):
        self.root = Path(root)
        self.hz = os.sysconf('SC_CLK_TCK')

    def path(self, name):
        return self.root / name.lstrip('/')

    def glob(self, pattern):
        return sorted(self.root.glob(pattern.lstrip('/')))

    def metadata(self, mode='shelf', workload='', interval=15, warmup=60):
        revision_state = safe_json(read(self.path('/storage/slot-manager/state.json')))
        revision_id = revision_state.get('current', '')
        revision = {}
        if re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', revision_id):
            revision = safe_json(read(self.path('/storage/slot-manager/revisions/' + revision_id + '/revision.json'), 1024*1024))
        return {'schema': SCHEMA, 'mode': mode, 'workload': workload or mode,
                'interval_s': interval, 'warmup_s': warmup, 'clock_ticks_per_s': self.hz,
                'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'kernel': read(self.path('/proc/sys/kernel/osrelease')),
                'revision': revision_id,
                'frontend_sha256': revision.get('files', {}).get('slot', {}).get('sha256'),
                'os_build': next((line.split('=',1)[1].strip('"') for line in (read(self.path('/etc/os-release')) or '').splitlines() if line.startswith('BUILD_ID=')), None),
                'core_hashes': {n: v.get('sha256') for n, v in revision.get('files', {}).items()
                                if n in ('mgba_libretro.so', 'gpsp_libretro.so')},
                'settings': settings(read(self.path('/storage/slotcontent/Config/slot.state'))),
                'units': {'current': 'uA', 'voltage': 'uV', 'charge': 'uAh',
                          'supply_temp': 'tenths Celsius', 'thermal_zone': 'millidegrees Celsius',
                          'cpuidle_time': 'us', 'cpufreq': 'kHz', 'devfreq': 'Hz',
                          'ondemand_sampling_rate': 'us', 'devfreq_polling_interval': 'ms'},
                'limits': ['PMIC averages are estimates, not a calibrated power meter.',
                           'RK817 corrects the gauge across suspend and can recalibrate at boot.',
                           'Process/service CPU is not a measurement of watts per service.',
                           'No samples or RTC wakeups are generated during deep suspend.']}

    def audio_pcm(self):
        text=read(self.path('/proc/asound/card0/pcm0p/sub0/hw_params'),2048) or ''
        rate=re.search(r'^rate:\s*(\d+)',text,re.M)
        channels=re.search(r'^channels:\s*(\d+)',text,re.M)
        format_name=re.search(r'^format:\s*([A-Z0-9_]+)',text,re.M)
        if not (rate and channels and format_name): return None
        return {'rate_hz':int(rate[1]),'channels':int(channels[1]),'format':format_name[1]}

    def audio_route(self):
        helper=self.path('/usr/bin/slot-audio-route')
        if not helper.is_file(): return None
        try:
            result=subprocess.run([str(helper),'--status'],capture_output=True,text=True,timeout=2)
            value=safe_json(result.stdout[:4096])
            if result.returncode or type(value.get('headphones')) is not bool or type(value.get('correct')) is not bool or value.get('route') not in ('HP','SPK'):
                return None
            return {key:value[key] for key in ('headphones','route','correct')}
        except (OSError,subprocess.SubprocessError): return None

    def sample(self):
        started, cpu_started = time.perf_counter(), time.process_time()
        row = {'schema': SCHEMA, 'wall_s': time.time(), 'monotonic_s': time.monotonic(),
               'boottime_s': time.clock_gettime(time.CLOCK_BOOTTIME),
               'boot_id': read(self.path('/proc/sys/kernel/random/boot_id'))}
        row['supplies'] = {p.name: {k: read(p / k, 128) for k in SUPPLY_FIELDS}
                           for p in self.glob('/sys/class/power_supply/*')[:8]}
        row['sensors'] = {}
        for pattern in ('/sys/class/backlight/*/brightness', '/sys/class/backlight/*/actual_brightness',
                        '/sys/class/backlight/*/max_brightness',
                        '/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq',
                        '/sys/class/devfreq/*/cur_freq', '/sys/class/thermal/thermal_zone*/temp'):
            for p in self.glob(pattern)[:16]:
                row['sensors']['/' + str(p.relative_to(self.root))] = integer(read(p, 128))
        row['governors'] = {p.parent.name: read(p, 128) for p in self.glob('/sys/devices/system/cpu/cpufreq/policy*/scaling_governor')[:8]}
        row['frequency_limits'] = {p.parent.name: {
            k: integer(read(p.parent / k, 64)) for k in ('scaling_min_freq', 'scaling_max_freq')}
            for p in self.glob('/sys/devices/system/cpu/cpufreq/policy*/scaling_governor')[:8]}
        row['cpu_governor_tunables'] = {}
        for p in self.glob('/sys/devices/system/cpu/cpufreq/policy*/scaling_governor')[:8]:
            if read(p, 128) != 'ondemand':
                continue
            # Kernels expose either per-policy or shared ondemand parameters.
            local = p.parent / 'ondemand'
            directory = local if local.is_dir() else p.parent.parent / 'ondemand'
            row['cpu_governor_tunables'][p.parent.name] = {
                k: integer(read(directory / k, 64)) for k in ONDEMAND_PARAMETERS}
        row['gpu_policy'] = {p.parent.name: {
            'governor': read(p, 128),
            **{k: integer(read(p.parent / k, 64))
               for k in ('min_freq', 'max_freq', 'polling_interval')}}
            for p in self.glob('/sys/class/devfreq/*/governor')[:16]}
        row['boost'] = integer(read(self.path('/sys/devices/system/cpu/cpufreq/boost'), 64))
        row['mem_sleep'] = read(self.path('/sys/power/mem_sleep'), 128)
        row['wifi'] = {p.name: read(p / 'operstate', 32)
                       for p in self.glob('/sys/class/net/*') if p.name.startswith(('wlan', 'wlp'))}
        row['audio_route'] = self.audio_route()
        row['audio_pcm'] = self.audio_pcm()
        row['settings'] = settings(read(self.path('/storage/slotcontent/Config/slot.state')))
        row['cpu'], row['system_counters'] = [], {}
        for line in (read(self.path('/proc/stat'), 65536) or '').splitlines():
            parts = line.split()
            if parts and parts[0] == 'cpu':
                row['cpu'] = [int(v) for v in parts[1:9]]
            if parts and parts[0] in ('ctxt', 'intr', 'softirq', 'processes'):
                row['system_counters'][parts[0]] = integer(parts[1])
        row['processes'] = {}
        for p in self.glob('/proc/[0-9]*/stat')[:MAX_PROCESSES]:
            text = read(p, 4096)
            if not text or '(' not in text or ')' not in text:
                continue
            try:
                tail = text.rsplit(')', 1)[1].split()
                ticks, start = int(tail[11]) + int(tail[12]), int(tail[19])
            except (ValueError, IndexError):
                continue
            comm = text.split('(', 1)[1].rsplit(')', 1)[0]
            group = read(p.parent / 'cgroup', 4096) or ''
            units = re.findall(r'([^/:\n]+\.service)(?:/|$)', group)
            row['processes'][p.parent.name] = {'comm': comm, 'ticks': ticks,
                                              'start_ticks': start,
                                              'service': units[-1] if units else None}
        row['idle'] = {}
        for p in self.glob('/sys/devices/system/cpu/cpu[0-9]*/cpuidle/state*/time')[:64]:
            name = '/' + str(p.parent.relative_to(self.root))
            row['idle'][name] = {'time_us': integer(read(p, 64)),
                                  'usage': integer(read(p.parent / 'usage', 64)),
                                  'name': read(p.parent / 'name', 64)}
        row['suspend_success'] = integer(read(self.path('/sys/power/suspend_stats/success'), 64))
        row['sample_cost'] = {'wall_ms': (time.perf_counter() - started) * 1000,
                              'cpu_ms': (time.process_time() - cpu_started) * 1000}
        return row


def electrical(row):
    candidates = [(name, data) for name, data in row.get('supplies', {}).items()
                  if data.get('type') == 'Battery' or name == 'battery']
    battery = candidates[0][1] if candidates else {}
    online = any(integer(v.get('online')) == 1 for v in row.get('supplies', {}).values())
    current = integer(battery.get('current_avg'))
    if current is None:
        current = integer(battery.get('current_now'))
    voltage = integer(battery.get('voltage_avg'))
    if voltage is None:
        voltage = integer(battery.get('voltage_now'))
    valid = (not online and battery.get('status') == 'Discharging' and current is not None
             and current <= 0 and voltage is not None and 2000000 <= voltage <= 5000000)
    return {'status': battery.get('status'), 'charger_online': online,
            'capacity_pct': integer(battery.get('capacity')),
            'current_uA': current, 'voltage_uV': voltage,
            'charge_uAh': integer(battery.get('charge_now')),
            'full_uAh': integer(battery.get('charge_full')),
            'battery_temp_tenths_c': integer(battery.get('temp')),
            'power_W': -current * voltage / 1e12 if valid else None,
            'discharge_mA': -current / 1000 if valid else None}


def load_capture(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Capture exceeds 64 MiB')
    metadata, rows, warnings = {}, [], []
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        try:
            record = json.loads(line)
        except ValueError:
            if i == len(lines) - 1:
                warnings.append('Incomplete final JSON row ignored')
                continue
            raise ValueError('Malformed capture row ' + str(i + 1))
        if not isinstance(record, dict):
            raise ValueError('Capture rows must be objects')
        if 'metadata' in record:
            metadata = record['metadata']
        elif 'supplies' in record and 'monotonic_s' in record:
            rows.append(record)
    return metadata, rows, warnings


def summarize(metadata, rows, warmup=None):
    if len(rows) < 2:
        raise ValueError('At least two samples are required')
    warmup = metadata.get('warmup_s', 60) if warmup is None else warmup
    if not math.isfinite(warmup) or warmup < 0:
        raise ValueError('Warmup must be finite and nonnegative')
    for row in rows:
        if not all(isinstance(row.get(k), (float, int)) and math.isfinite(row[k])
                   for k in ('boottime_s', 'monotonic_s')):
            raise ValueError('Missing or nonfinite sample clock')
    origin = rows[0]['boottime_s']
    interval = metadata.get('interval_s', 15)
    if not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ValueError('Invalid sample interval')
    chosen = [r for r in rows if r['boottime_s'] - origin >= warmup]
    warnings = []
    warmup_incomplete = len(chosen) < 2
    if warmup_incomplete:
        chosen = rows
        warnings.append('Capture too short for requested warmup; complete interval used')
    elapsed = chosen[-1]['boottime_s'] - chosen[0]['boottime_s']
    if elapsed <= 0:
        raise ValueError('Capture must advance CLOCK_BOOTTIME')
    energy, charge_integral, covered, sleep_s, gaps_s = 0., 0., 0., 0., 0.
    currents, powers, cpu_busy, process_cpu, service_cpu = [], [], [], {}, {}
    context_changes, counter_up, counter_jump, boot_change = set(), False, False, False
    interrupt_delta, ctxt_delta, total_cpu, busy_cpu = 0, 0, 0, 0
    idle_delta = {}
    first_e, last_e = electrical(chosen[0]), electrical(chosen[-1])
    initial_settings = chosen[0].get('settings', metadata.get('settings', {}))
    def conditions(row):
        return {'wifi': row.get('wifi'), 'governors': row.get('governors'),
                'frequency_limits': row.get('frequency_limits'), 'boost': row.get('boost'),
                **{k: row.get(k) for k in POLICY_CONDITIONS},
                'mem_sleep': row.get('mem_sleep'),
                'backlight': {k: v for k, v in row.get('sensors', {}).items()
                              if '/backlight/' in k}}
    initial_conditions = conditions(chosen[0])
    for a, b in zip(chosen, chosen[1:]):
        dt = b['boottime_s'] - a['boottime_s']
        dm = b['monotonic_s'] - a['monotonic_s']
        if dt <= 0 or dm < 0:
            raise ValueError('Non-monotonic capture')
        same_boot = a.get('boot_id', metadata.get('boot_id')) == b.get('boot_id', metadata.get('boot_id'))
        if not same_boot:
            boot_change = True
            gaps_s += dt
            continue
        sleep = max(0., dt - dm)
        sleep_s += sleep
        ea, eb = electrical(a), electrical(b)
        if ea['charge_uAh'] is not None and eb['charge_uAh'] is not None and eb['charge_uAh'] - ea['charge_uAh'] > 2000 and not eb['charger_online']:
            counter_up = True
        if ea['charge_uAh'] is not None and eb['charge_uAh'] is not None and ea['discharge_mA'] is not None and eb['discharge_mA'] is not None:
            expected_uAh = (ea['discharge_mA'] + eb['discharge_mA']) * .5 * dt / 3.6
            if abs((ea['charge_uAh']-eb['charge_uAh'])-expected_uAh) > max(5000, expected_uAh * 2):
                counter_jump = True
        later_settings = b.get('settings', initial_settings)
        for k in initial_settings.keys() | later_settings.keys():
            if later_settings.get(k) != initial_settings.get(k):
                context_changes.add(k)
        for k, value in conditions(b).items():
            if value != initial_conditions[k]:
                context_changes.add(k)
        suspended = sleep > 2 or (a.get('suspend_success') is not None and b.get('suspend_success') is not None and a['suspend_success'] != b['suspend_success'])
        gap = dt > interval * 2.5
        if suspended or gap:
            gaps_s += dt
            continue
        if ea['power_W'] is not None and eb['power_W'] is not None:
            energy += (ea['power_W'] + eb['power_W']) * .5 * dt / 3600
            charge_integral += (ea['discharge_mA'] + eb['discharge_mA']) * .5 * dt / 3600
            covered += dt
            powers.extend((ea['power_W'], eb['power_W']))
            currents.extend((ea['discharge_mA'], eb['discharge_mA']))
        ca, cb = a.get('cpu', []), b.get('cpu', [])
        if len(ca) >= 8 and len(cb) >= 8:
            delta = [y - x for x, y in zip(ca[:8], cb[:8])]
            if min(delta) >= 0 and sum(delta) > 0:
                total_cpu += sum(delta)
                busy_cpu += sum(delta) - delta[3] - delta[4]
        hz = metadata.get('clock_ticks_per_s', 100)
        for pid, p in b.get('processes', {}).items():
            prev = a.get('processes', {}).get(pid)
            if prev is None or p.get('start_ticks') != prev.get('start_ticks'):
                continue
            seconds = (p['ticks'] - prev['ticks']) / hz
            if seconds < 0:
                continue
            process_cpu[p['comm']] = process_cpu.get(p['comm'], 0) + seconds
            if p.get('service'):
                service_cpu[p['service']] = service_cpu.get(p['service'], 0) + seconds
        for k, value in b.get('idle', {}).items():
            prev = a.get('idle', {}).get(k)
            if prev and prev.get('time_us') is not None and value.get('time_us') is not None:
                delta = value['time_us'] - prev['time_us']
                if delta >= 0:
                    idle_delta[k] = idle_delta.get(k, 0) + delta / 1e6
        for key, target in (('intr', 'intr'), ('ctxt', 'ctxt')):
            x = a.get('system_counters', {}).get(key)
            y = b.get('system_counters', {}).get(key)
            if x is not None and y is not None and y >= x:
                if target == 'intr':
                    interrupt_delta += y - x
                else:
                    ctxt_delta += y - x
    awake_covered = elapsed - gaps_s
    all_unplugged = all(not electrical(r)['charger_online'] and electrical(r)['status'] == 'Discharging' for r in chosen)
    if not all_unplugged:
        warnings.append('Charger/status changed; this is not a matched unplugged run')
    if sleep_s > 2:
        warnings.append('Suspend intervals excluded from power integration; RK817 sleep correction makes charge deltas coarse')
    if gaps_s > 0:
        warnings.append('Unsampled intervals excluded; endpoint current cannot measure sleep/off power')
    if boot_change:
        warnings.append('Boot changed; gauge may recalibrate. No off-state current is inferred')
    if counter_up:
        warnings.append('Unplugged charge counter increased: possible gauge recalibration')
    if counter_jump:
        warnings.append('Charge counter jumped relative to sampled current; gauge delta is unreliable')
    if context_changes:
        warnings.append('Settings changed: ' + ', '.join(sorted(context_changes)))
    if covered < 600:
        warnings.append('Less than 10 minutes of valid awake discharge; repeat a longer matched run')
    if metadata.get('schema', 1) < SCHEMA:
        warnings.append('Legacy collector: complete policy context unavailable; automatic A/B qualification disabled')
    missing_policy = any(k not in r for r in chosen for k in POLICY_CONDITIONS)
    if metadata.get('schema', 1) >= SCHEMA and missing_policy:
        warnings.append('Missing CPU/GPU policy context; automatic A/B qualification disabled')
    if covered < awake_covered - 1:
        warnings.append('Some awake intervals lack valid negative discharge current/voltage readings')
    mean_power = energy * 3600 / covered if covered else None
    mean_current = charge_integral * 3600 / covered if covered else None
    counter_drop = (first_e['charge_uAh'] - last_e['charge_uAh']) / 1000 if first_e['charge_uAh'] is not None and last_e['charge_uAh'] is not None else None
    qualify = (metadata.get('mode', 'shelf') in ('shelf', 'gameplay') and all_unplugged
               and covered >= 600 and covered >= elapsed - 1 and gaps_s <= 1
               and not counter_up and not counter_jump and not context_changes and not boot_change
               and not warmup_incomplete and metadata.get('schema', 1) >= SCHEMA
               and not missing_policy)
    charge_projection = first_e['full_uAh'] / 1000 / mean_current if qualify and mean_current and first_e['full_uAh'] else None
    overhead = [r.get('sample_cost', {}) for r in chosen]
    temperatures = {}
    for r in chosen:
        for k, value in r.get('sensors', {}).items():
            if '/thermal_zone' in k and value is not None:
                temperatures.setdefault(k, []).append(value / 1000)
    return {'schema': SCHEMA, 'metadata': metadata, 'samples': len(rows),
            'analyzed_samples': len(chosen), 'warmup_s': warmup, 'elapsed_s': elapsed,
            'awake_discharge_covered_s': covered, 'suspend_s': sleep_s,
            'excluded_gap_s': gaps_s, 'mean_power_W': mean_power,
            'power_min_W': min(powers) if powers else None, 'power_max_W': max(powers) if powers else None,
            'mean_current_mA': mean_current, 'sampled_awake_energy_Wh': energy,
            'current_integral_mAh': charge_integral, 'gauge_charge_drop_mAh': counter_drop,
            'gauge_full_mAh': first_e['full_uAh'] / 1000 if first_e['full_uAh'] else None,
            'capacity_start_pct': first_e['capacity_pct'], 'capacity_end_pct': last_e['capacity_pct'],
            'gauge_based_full_capacity_projection_h': charge_projection,
            'projection_label': 'Fixed-workload extrapolation from gauge capacity and sampled current; not measured runtime',
            'comparable_awake_run': qualify, 'settings': initial_settings,
            'conditions': initial_conditions,
            'settings_changed': sorted(context_changes), 'warnings': warnings,
            'cpu_all_cores_busy_pct': busy_cpu / total_cpu * 100 if total_cpu else None,
            'process_cpu_one_core_pct': {k: v / awake_covered * 100 for k, v in sorted(process_cpu.items(), key=lambda x: -x[1])} if awake_covered > 0 else {},
            'service_cpu_one_core_pct': {k: v / awake_covered * 100 for k, v in sorted(service_cpu.items(), key=lambda x: -x[1])} if awake_covered > 0 else {},
            'cpu_idle_residency_s': idle_delta,
            'interrupts_per_awake_s': interrupt_delta / awake_covered if awake_covered > 0 and interrupt_delta else None,
            'context_switches_per_awake_s': ctxt_delta / awake_covered if awake_covered > 0 and ctxt_delta else None,
            'soc_temperature_c': {k: {'min': min(v), 'max': max(v), 'mean': statistics.mean(v)} for k, v in temperatures.items()},
            'sampler_cpu_ms': sum(v['cpu_ms'] for v in overhead if 'cpu_ms' in v) if any('cpu_ms' in v for v in overhead) else None,
            'sampler_max_sample_wall_ms': max((v['wall_ms'] for v in overhead if 'wall_ms' in v), default=None)}


def compare(a, b, vary=(), vary_conditions=()):
    reasons = []
    if not a.get('comparable_awake_run') or not b.get('comparable_awake_run'):
        reasons.append('Both captures must be qualified awake discharge runs')
    if any(r.get('metadata', {}).get('schema', 1) < SCHEMA for r in (a, b)):
        reasons.append('Both collectors must include complete CPU/GPU policy context')
    for k in ('mode', 'workload', 'kernel', 'core_hashes', 'revision', 'frontend_sha256', 'os_build'):
        if a.get('metadata', {}).get(k) != b.get('metadata', {}).get(k):
            reasons.append('Different ' + k)
    if "enhanced_audio" in vary and any("enhanced_audio" not in report.get("settings", {}) for report in (a,b)):
        reasons.append("Both captures must record the Enhanced Audio setting")
    if "enhanced_audio" in vary and any(not isinstance(report.get("conditions",{}).get("audio_route"),dict) or not report["conditions"]["audio_route"].get("correct") for report in (a,b)):
        reasons.append("Both audio captures need verified output routing")
    if "enhanced_audio" in vary and any(not report.get("conditions",{}).get("audio_pcm") for report in (a,b)):
        reasons.append("Both audio captures need an active PCM output")
    if "enhanced_audio" in vary and any(not all(report.get("metadata",{}).get(k) for k in ("revision","frontend_sha256","os_build","core_hashes")) for report in (a,b)):
        reasons.append("Both audio captures need build and core identity")
    condition_changes = {}
    for k in ('wifi', 'governors', 'frequency_limits', 'boost', 'mem_sleep', 'backlight') + POLICY_CONDITIONS:
        if a.get('conditions', {}).get(k) != b.get('conditions', {}).get(k):
            condition_changes[k] = {'baseline': a.get('conditions', {}).get(k),
                                    'candidate': b.get('conditions', {}).get(k)}
            if not (k=='audio_pcm' and 'enhanced_audio' in vary) and (k not in VARY_CONDITIONS or k not in vary_conditions):
                if k != 'backlight' or 'brightness' not in vary:
                    reasons.append('Different ' + k)
    changes = []
    for k in a.get('settings', {}).keys() | b.get('settings', {}).keys():
        if a.get('settings', {}).get(k) != b.get('settings', {}).get(k):
            changes.append(k)
            if k not in vary:
                reasons.append('Uncontrolled setting: ' + k)
    good = not reasons
    x, y = a.get('mean_power_W'), b.get('mean_power_W')
    return {'comparable': good, 'reasons': reasons, 'varied_settings': sorted(changes),
            'condition_changes': condition_changes,
            'baseline_W': x, 'candidate_W': y,
            'power_reduction_pct': (x-y)/x*100 if good and x and y is not None else None,
            'runtime_multiplier_same_energy': x/y if good and x and y and y > 0 else None,
            'interpretation': 'Sampled PMIC comparison; repeat matched runs before accepting a firmware change'}


def retention(before, after):
    ea, eb = electrical(before), electrical(after)
    dt = after['wall_s'] - before['wall_s']
    if dt <= 0:
        raise ValueError('Endpoint wall clock did not advance')
    return {'elapsed_wall_s': dt, 'different_boots': before.get('boot_id') != after.get('boot_id'),
            'capacity_before_pct': ea['capacity_pct'], 'capacity_after_pct': eb['capacity_pct'],
            'gauge_charge_change_mAh': (eb['charge_uAh']-ea['charge_uAh'])/1000 if ea['charge_uAh'] is not None and eb['charge_uAh'] is not None else None,
            'off_current_mA': None, 'off_power_W': None,
            'interpretation': 'Coarse gauge retention observation, including shutdown/boot and possible RK817 recalibration; cannot determine powered-off drain'}


def export_report(folder, metadata, rows, warmup=None, warnings=()):
    summary = summarize(metadata, rows, warmup)
    if warnings:
        summary['warnings'].extend(warnings)
        summary['comparable_awake_run'] = False
        summary['gauge_based_full_capacity_projection_h'] = None
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    columns = ['boottime_s', 'monotonic_s', 'status', 'charger_online', 'capacity_pct',
               'current_uA', 'voltage_uV', 'charge_uAh', 'power_W']
    with (folder/'samples.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            e = electrical(row)
            writer.writerow({k: row[k] if k in row else e.get(k) for k in columns})
    def fmt(value, digits=2):
        return f'{value:.{digits}f}' if isinstance(value, (int, float)) else 'Unavailable'
    lines = ['# Battery profile', '',
             f"Analyzed {summary['elapsed_s']/60:.1f} minutes after {summary['warmup_s']:.0f} seconds of warmup.", '',
             '| Measurement | Result |', '| --- | --- |',
             f"| Average battery power | {fmt(summary['mean_power_W'])} W |",
             f"| Average discharge current | {fmt(summary['mean_current_mA'], 1)} mA |",
             f"| Gauge charge drop | {fmt(summary['gauge_charge_drop_mAh'], 1)} mAh |",
             f"| Sampled awake energy | {fmt(summary['sampled_awake_energy_Wh'], 3)} Wh |",
             f"| CPU busy, all cores | {fmt(summary['cpu_all_cores_busy_pct'], 1)}% |", '',
             'Power uses PMIC averages. Process CPU does not measure watts per process.', '']
    if summary['warnings']:
        lines += ['Observations:', ''] + ['- '+v for v in summary['warnings']] + ['']
    lines += ['See summary.json for conditions, coverage, attribution and qualification.']
    (folder/'report.md').write_text('\n'.join(lines)+'\n')
    return summary


class StopCapture(Exception):
    pass


def record(args):
    collector = Collector()
    if collector.path('/run/slot-usb/active').exists():
        raise ValueError('Exit USB storage mode before recording')
    if not 5 <= args.interval <= 300 or not args.interval <= args.duration <= 86400:
        raise ValueError('Interval must be 5..300 seconds, duration interval..86400')
    if not math.isfinite(args.warmup) or not 0 <= args.warmup < args.duration:
        raise ValueError('Warmup must be finite, nonnegative and shorter than duration')
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    meta = collector.metadata(args.mode, args.workload, args.interval, args.warmup)
    initial = collector.sample()
    if electrical(initial)['charger_online'] and not args.allow_charging:
        folder.rmdir()
        raise ValueError('Unplug before a discharge capture, or use --allow-charging for telemetry only')
    rows, reason = [initial], 'duration'
    old = {}
    def stop(signum, frame):
        raise StopCapture()
    for sig in (signal.SIGTERM, signal.SIGINT):
        old[sig] = signal.signal(sig, stop)
    start = initial['boottime_s']
    try:
        with (folder/'samples.jsonl').open('x') as stream:
            stream.write(json.dumps({'metadata': meta})+'\n')
            stream.write(json.dumps(initial)+'\n')
            stream.flush()
            try:
                while rows[-1]['boottime_s']-start < args.duration:
                    time.sleep(min(args.interval, max(0., args.duration-(rows[-1]['boottime_s']-start))))
                    row = collector.sample()
                    line = json.dumps(row)+'\n'
                    if stream.tell()+len(line.encode()) > MAX_BYTES:
                        reason = 'byte_limit'
                        break
                    stream.write(line)
                    stream.flush()
                    rows.append(row)
                    e = electrical(row)
                    if e['charger_online'] and not args.allow_charging:
                        reason = 'charger_connected'
                        break
                    if e['capacity_pct'] is not None and e['capacity_pct'] <= 15 and not e['charger_online']:
                        reason = 'low_battery'
                        break
            except StopCapture:
                reason = 'interrupted'
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
    meta['stop_reason'] = reason
    meta['profiler_max_rss_KiB'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if len(rows) >= 2:
        result = export_report(folder, meta, rows)
    else:
        result = {'metadata': meta, 'samples': len(rows), 'warnings': ['Interrupted before a second sample']}
        (folder/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'output': str(folder), 'stop_reason': reason, 'samples': len(rows)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('record')
    p.add_argument('--duration', type=int, default=900)
    p.add_argument('--interval', type=int, default=15)
    p.add_argument('--warmup', type=float, default=60)
    p.add_argument('--mode', choices=('shelf', 'gameplay', 'sleep'), default='shelf')
    p.add_argument('--workload', default='')
    p.add_argument('--allow-charging', action='store_true')
    p.add_argument('--output', required=True)
    p = sub.add_parser('analyze')
    p.add_argument('capture')
    p.add_argument('--output', required=True)
    p.add_argument('--warmup', type=float)
    p.add_argument('--context', help='Optional local context JSON; only known settings/revision fields are imported')
    p = sub.add_parser('snapshot')
    p.add_argument('--output', required=True)
    p = sub.add_parser('compare')
    p.add_argument('baseline')
    p.add_argument('candidate')
    p.add_argument('--vary', action='append', choices=SETTINGS, default=[])
    p.add_argument('--vary-condition', action='append', choices=VARY_CONDITIONS, default=[],
                   help='Declare an intentional Wi-Fi/CPU/GPU experiment; all changed values remain in the report')
    p = sub.add_parser('retention')
    p.add_argument('before')
    p.add_argument('after')
    args = parser.parse_args()
    try:
        if args.command == 'record':
            record(args)
        elif args.command == 'snapshot':
            with Path(args.output).open('x') as stream:
                json.dump(Collector().sample(), stream)
        elif args.command == 'analyze':
            meta, rows, warnings = load_capture(args.capture)
            if args.context:
                context = safe_json(read(args.context, MAX_BYTES))
                meta['settings'] = settings(context.get('settings'))
                meta['revision'] = context.get('manager', {}).get('current')
                meta['mode'], meta['workload'] = 'shelf', 'shelf'
            summary = export_report(args.output, meta, rows, args.warmup, warnings)
            print(json.dumps({k: summary[k] for k in ('samples', 'mean_power_W', 'mean_current_mA', 'comparable_awake_run', 'warnings')}, indent=2))
        elif args.command == 'compare':
            print(json.dumps(compare(json.loads(Path(args.baseline).read_text()), json.loads(Path(args.candidate).read_text()), args.vary, args.vary_condition), indent=2))
        elif args.command == 'retention':
            print(json.dumps(retention(json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text())), indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
