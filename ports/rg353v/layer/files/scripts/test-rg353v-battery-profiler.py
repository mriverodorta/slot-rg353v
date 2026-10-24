#!/usr/bin/env python3
"""Battery accounting and read-only collection regression tests."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('battery', ROOT/'ports/rg353v/battery-profiler.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def capture():
    meta = {'schema': m.SCHEMA, 'mode': 'shelf', 'workload': 'shelf', 'kernel': 'test',
            'interval_s': 15, 'warmup_s': 0, 'clock_ticks_per_s': 100,
            'core_hashes': {'mgba_libretro.so':'b'*64}, 'revision':'fixture',
            'frontend_sha256':'a'*64,'os_build':'fixture-os', 'settings': {'brightness': '9'}}
    rows = []
    for t in range(0, 901, 15):
        rows.append({'boottime_s': t, 'monotonic_s': t, 'wall_s': 1000+t, 'boot_id': 'a',
                     'supplies': {'battery': {'type': 'Battery', 'status': 'Discharging',
                          'current_avg': '-500000', 'voltage_avg': '4000000',
                          'charge_now': str(round(3000000 - 500000*t/3600)),
                          'charge_full': '3200000', 'capacity': '90'},
                          'charger': {'online': '0'}},
                     'settings': {'brightness': '9'}, 'wifi': {'wlan0': 'up'},
                     'governors': {'policy0': 'ondemand'},
                     'audio_route': {'headphones':False,'route':'SPK','correct':True},
                     'audio_pcm': {'rate_hz':32768,'channels':2,'format':'S16_LE'},
                     'cpu_governor_tunables': {'policy0': {'sampling_rate': 8000}},
                     'gpu_policy': {'gpu': {'governor': 'simple_ondemand',
                                           'min_freq': 400000000, 'max_freq': 800000000,
                                           'polling_interval': 100}},
                     'sensors': {'/sys/class/backlight/backlight/brightness': 255},
                     'cpu': [t*10, 0, 0, t*390, 0, 0, 0, 0],
                     'processes': {'5': {'comm': 'slot', 'ticks': t*10,
                         'start_ticks': 100, 'service': 'slot-rg353v.service'}},
                     'system_counters': {'intr': t*100, 'ctxt': t*200},
                     'idle': {'cpu0/state1': {'time_us': t*900000, 'usage': t, 'name': 'cpu-sleep'}},
                     'suspend_success': 0})
    return meta, rows


class BatteryTests(unittest.TestCase):
    def test_audio_comparison_requires_recorded_mode_and_rejects_picture_or_revision_changes(self):
        meta,rows=capture();a=m.summarize(meta,rows);b=copy.deepcopy(a)
        self.assertFalse(m.compare(a,b,vary=['enhanced_audio'])['comparable'])
        a['settings']['enhanced_audio']='0';b['settings']['enhanced_audio']='1'
        self.assertFalse(m.compare(a,b)['comparable'])
        self.assertTrue(m.compare(a,b,vary=['enhanced_audio'])['comparable'])
        b['settings']['shader_gbc']='different'
        self.assertFalse(m.compare(a,b,vary=['enhanced_audio'])['comparable'])
        del b['settings']['shader_gbc'];b['metadata']['revision']='another-build'
        self.assertFalse(m.compare(a,b,vary=['enhanced_audio'])['comparable'])

    def test_audio_route_changes_or_missing_route_cannot_be_claimed_as_audio_savings(self):
        meta,rows=capture();a=m.summarize(meta,rows);b=copy.deepcopy(a)
        a['settings']['enhanced_audio']='0';b['settings']['enhanced_audio']='1'
        self.assertTrue(m.compare(a,b,vary=['enhanced_audio'])['comparable'])
        b['conditions']['audio_route']={'headphones':True,'route':'HP','correct':True}
        self.assertFalse(m.compare(a,b,vary=['enhanced_audio'])['comparable'])
        b['conditions']['audio_route']=None
        self.assertFalse(m.compare(a,b,vary=['enhanced_audio'])['comparable'])
        for row in rows[30:]:row['audio_route']={'headphones':True,'route':'HP','correct':True}
        self.assertFalse(m.summarize(meta,rows)['comparable_awake_run'])

    def test_audio_pcm_reads_actual_hardware_rate_and_closed_pcm_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'proc/asound/card0/pcm0p/sub0/hw_params';path.parent.mkdir(parents=True)
            path.write_text('format: S16_LE\nchannels: 2\nrate: 48000 (48000/1)\n')
            self.assertEqual(m.Collector(Path(tmp)).audio_pcm(),{'rate_hz':48000,'channels':2,'format':'S16_LE'})
            path.write_text('closed');self.assertIsNone(m.Collector(Path(tmp)).audio_pcm())
        meta,rows=capture();a=m.summarize(meta,rows);b=copy.deepcopy(a)
        a['settings']['enhanced_audio']='0';b['settings']['enhanced_audio']='1';b['conditions']['audio_pcm']['rate_hz']=48000
        self.assertTrue(m.compare(a,b,vary=['enhanced_audio'])['comparable'])
        self.assertFalse(m.compare(a,b)['comparable'])

    def test_route_probe_is_status_only_bounded_and_filters_nonrouting_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper=Path(tmp)/'usr/bin/slot-audio-route';helper.parent.mkdir(parents=True);helper.touch()
            collector=m.Collector(Path(tmp))
            with patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"headphones":false,"route":"SPK","correct":true,"secret":"omit"}')) as run:
                self.assertEqual(collector.audio_route(),{'headphones':False,'route':'SPK','correct':True})
                self.assertEqual(run.call_args.args[0],[str(helper),'--status']);self.assertEqual(run.call_args.kwargs['timeout'],2)
            with patch.object(m.subprocess,'run',side_effect=m.subprocess.TimeoutExpired('probe',2)):
                self.assertIsNone(collector.audio_route())

    def test_audio_and_independent_console_settings_are_recorded_but_secrets_are_not(self):
        values=m.settings('enhanced_audio=1\nshader_gbc=sharp_lcd\nperfect_shader_gbc=lcd3x\ncolour_correction_gbc=1\npassword=secret\nssid=private')
        self.assertEqual(set(values),{'enhanced_audio','shader_gbc','perfect_shader_gbc','colour_correction_gbc'})

    def test_units_integration_and_cpu_attribution(self):
        meta, rows = capture()
        r = m.summarize(meta, rows)
        self.assertTrue(r['comparable_awake_run'])
        self.assertAlmostEqual(r['mean_power_W'], 2)
        self.assertAlmostEqual(r['mean_current_mA'], 500)
        self.assertAlmostEqual(r['sampled_awake_energy_Wh'], .5)
        self.assertAlmostEqual(r['gauge_charge_drop_mAh'], 125)
        self.assertAlmostEqual(r['cpu_all_cores_busy_pct'], 2.5)
        self.assertEqual(r['service_cpu_one_core_pct']['slot-rg353v.service'], 10)
        self.assertEqual(r['interrupts_per_awake_s'], 100)
        self.assertEqual(r['cpu_idle_residency_s']['cpu0/state1'], 810)
        self.assertAlmostEqual(r['gauge_based_full_capacity_projection_h'], 6.4)

    def test_time_weighting_irregular_samples(self):
        meta, rows = capture()
        rows = [rows[0], rows[1], rows[3]]
        rows[1]['supplies']['battery']['current_avg'] = '-1000000'
        r = m.summarize(meta, rows)
        self.assertAlmostEqual(r['mean_power_W'], 3)
        self.assertEqual(r['awake_discharge_covered_s'], 45)
        self.assertFalse(r['comparable_awake_run'])

    def test_sleep_gap_never_extrapolates_endpoint_current(self):
        meta, rows = capture()
        rows = [rows[0], rows[1], rows[2]]
        rows[-1]['boottime_s'] += 600
        rows[-1]['suspend_success'] = 1
        r = m.summarize(meta, rows)
        self.assertEqual(r['awake_discharge_covered_s'], 15)
        self.assertEqual(r['suspend_s'], 600)
        self.assertIsNone(r['gauge_based_full_capacity_projection_h'])
        meta['mode'] = 'sleep'
        self.assertFalse(m.summarize(meta, capture()[1])['comparable_awake_run'])

    def test_charging_and_wrong_sign_do_not_become_discharge_watts(self):
        meta, rows = capture()
        rows[5]['supplies']['charger']['online'] = '1'
        self.assertIsNone(m.electrical(rows[5])['power_W'])
        self.assertFalse(m.summarize(meta, rows)['comparable_awake_run'])
        rows[5]['supplies']['charger']['online'] = '0'
        rows[5]['supplies']['battery']['current_avg'] = '500000'
        self.assertIsNone(m.electrical(rows[5])['power_W'])
        self.assertFalse(m.summarize(meta, rows)['comparable_awake_run'])

    def test_gauge_correction_is_flagged_separately(self):
        meta, rows = capture()
        rows[5]['supplies']['battery']['charge_now'] = '2800000'
        r = m.summarize(meta, rows)
        self.assertAlmostEqual(r['mean_power_W'], 2)
        self.assertFalse(r['comparable_awake_run'])
        self.assertTrue(any('counter jumped' in x for x in r['warnings']))

    def test_within_run_context_changes_are_rejected(self):
        for field, value in [('settings', {}), ('wifi', {'wlan0': 'down'}),
                             ('governors', {'policy0': 'performance'}), ('sensors', {})]:
            meta, rows = capture()
            rows[3][field] = value
            self.assertFalse(m.summarize(meta, rows)['comparable_awake_run'], field)

    def test_new_render_choices_are_recorded_and_invalidate_changed_runs(self):
        for key in ('perfect_shader_gba', 'perfect_shader_gb',
                    'perfect_colour_correction', 'show_fps', 'blue_light'):
            self.assertEqual(m.settings(key + '=value\npassword=SECRET'), {key: 'value'})
            meta, rows = capture()
            rows[3]['settings'][key] = 'changed'
            result = m.summarize(meta, rows)
            self.assertFalse(result['comparable_awake_run'], key)
            self.assertIn(key, result['settings_changed'])

    def test_pid_reuse_does_not_invent_cpu_work(self):
        meta, rows = capture()
        rows = rows[:2]
        rows[-1]['processes']['5'].update(ticks=99999999, start_ticks=200)
        self.assertEqual(m.summarize(meta, rows)['service_cpu_one_core_pct'], {})

    def test_policy_changes_within_a_run_are_rejected(self):
        for key in m.POLICY_CONDITIONS:
            meta, rows = capture()
            rows[3][key] = {}
            r = m.summarize(meta, rows)
            self.assertFalse(r['comparable_awake_run'])
            self.assertIn(key, r['settings_changed'])

    def test_policy_experiment_must_be_declared_and_reports_actual_changes(self):
        a = m.summarize(*capture()); b = copy.deepcopy(a)
        b['conditions']['cpu_governor_tunables']['policy0']['sampling_rate'] = 20000
        self.assertFalse(m.compare(a, b)['comparable'])
        r = m.compare(a, b, vary_conditions=['cpu_governor_tunables'])
        self.assertTrue(r['comparable'])
        self.assertEqual(r['condition_changes']['cpu_governor_tunables']['candidate']['policy0']['sampling_rate'], 20000)
        b['conditions']['gpu_policy']['gpu']['min_freq'] = 200000000
        self.assertFalse(m.compare(a, b, vary_conditions=['cpu_governor_tunables'])['comparable'])
        self.assertTrue(m.compare(a, b, vary_conditions=list(m.POLICY_CONDITIONS))['comparable'])
        # A policy declaration cannot bypass differing kernels or Wi-Fi state.
        b['conditions']['wifi'] = {'wlan0': 'down'}
        self.assertFalse(m.compare(a, b, vary_conditions=list(m.POLICY_CONDITIONS))['comparable'])
        b['conditions']['wifi'] = a['conditions']['wifi']
        b['metadata']['kernel'] = 'different-kernel'
        self.assertFalse(m.compare(a, b, vary_conditions=list(m.POLICY_CONDITIONS))['comparable'])

    def test_explicit_wifi_experiment_only_allows_wifi_difference(self):
        a = m.summarize(*capture()); b = copy.deepcopy(a)
        b['conditions']['wifi'] = {'wlan0': 'down'}
        self.assertFalse(m.compare(a, b)['comparable'])
        result = m.compare(a, b, vary_conditions=['wifi'])
        self.assertTrue(result['comparable'])
        self.assertEqual(result['condition_changes']['wifi']['candidate'], {'wlan0': 'down'})
        b['conditions']['gpu_policy']['gpu']['min_freq'] = 200000000
        self.assertFalse(m.compare(a, b, vary_conditions=['wifi'])['comparable'])
        b['conditions']['gpu_policy'] = a['conditions']['gpu_policy']
        b['settings']['brightness'] = '4'
        self.assertFalse(m.compare(a, b, vary_conditions=['wifi'])['comparable'])

    def test_older_policy_incomplete_capture_cannot_auto_qualify(self):
        meta, rows = capture(); meta['schema'] = 2
        for row in rows:
            for key in m.POLICY_CONDITIONS:
                row.pop(key)
        r = m.summarize(meta, rows)
        self.assertAlmostEqual(r['mean_power_W'], 2)
        self.assertFalse(r['comparable_awake_run'])
        old_summary = m.summarize(*capture())
        old_summary['metadata']['schema'] = 2
        self.assertFalse(m.compare(old_summary, old_summary)['comparable'])

    def test_schema_three_missing_policy_data_cannot_auto_qualify(self):
        meta, rows = capture()
        for row in rows:
            row.pop('gpu_policy')
        self.assertFalse(m.summarize(meta, rows)['comparable_awake_run'])

    def test_no_unknown_battery_metrics_invented(self):
        self.assertIsNone(m.electrical({})['power_W'])
        self.assertIsNone(m.electrical(capture()[1][0])['battery_temp_tenths_c'])

    def test_legacy_data_keeps_power_but_cannot_auto_qualify(self):
        meta, rows = capture(); meta.pop('schema')
        r = m.summarize(meta, rows)
        self.assertAlmostEqual(r['mean_power_W'], 2)
        self.assertFalse(r['comparable_awake_run'])
        self.assertIsNone(r['gauge_based_full_capacity_projection_h'])
        self.assertIsNone(r['sampler_cpu_ms'])
        self.assertIsNone(r['sampler_max_sample_wall_ms'])

    def test_comparison_demands_matched_conditions(self):
        a = m.summarize(*capture()); b = copy.deepcopy(a)
        b['mean_power_W'] = 1.5
        self.assertAlmostEqual(m.compare(a, b)['power_reduction_pct'], 25)
        b['settings']['brightness'] = '5'
        b['conditions']['backlight'] = {'/sys/class/backlight/backlight/brightness': 100}
        self.assertFalse(m.compare(a, b)['comparable'])
        self.assertTrue(m.compare(a, b, ['brightness'])['comparable'])
        b['conditions']['wifi'] = {'wlan0': 'down'}
        self.assertFalse(m.compare(a, b, ['brightness'])['comparable'])

    def test_off_state_endpoints_never_claim_current(self):
        _, rows = capture()
        rows[-1]['boot_id'] = 'b'
        r = m.retention(rows[0], rows[-1])
        self.assertTrue(r['different_boots'])
        self.assertIsNone(r['off_current_mA'])
        self.assertIsNone(r['off_power_W'])

    def test_bad_clocks_and_warmups_are_rejected(self):
        meta, rows = capture()
        for bad in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): m.summarize(meta, rows, bad)
        rows[1]['boottime_s'] = float('nan')
        with self.assertRaises(ValueError): m.summarize(meta, rows)

    def test_export_and_incomplete_tail(self):
        meta, rows = capture()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'raw.jsonl'
            p.write_text(json.dumps({'metadata': meta})+'\n'+ '\n'.join(map(json.dumps, rows))+'\n{')
            head, samples, warnings = m.load_capture(p)
            self.assertEqual(len(samples), 61)
            r = m.export_report(Path(d)/'out', head, samples, warnings=warnings)
            self.assertFalse(r['comparable_awake_run'])
            self.assertIn('Incomplete final JSON', (Path(d)/'out/report.md').read_text())
            self.assertEqual(len((Path(d)/'out/samples.csv').read_text().splitlines()), 62)
            p.write_text('{}\n{\n{}')
            with self.assertRaises(ValueError): m.load_capture(p)

    def test_fixture_collector_uses_allowlist_and_parses_proc(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            def put(p, s):
                p = root/p; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(s)
            put('storage/slotcontent/Config/slot.state', 'brightness=9\npassword=SECRET\nrecents=private\n')
            put('proc/stat', 'cpu 1 2 3 4 5 6 7 8\nintr 100 1\nctxt 200\n')
            tail = ['S'] + ['0']*49; tail[11]='22'; tail[12]='3'; tail[19]='555'
            put('proc/123/stat', '123 (worker (x)) '+' '.join(tail))
            put('proc/123/cgroup', '0::/system.slice/test.service\n')
            put('sys/class/power_supply/battery/type', 'Battery')
            put('sys/class/power_supply/battery/current_avg', '-500000')
            c = m.Collector(root)
            with patch.object(m.time, 'CLOCK_BOOTTIME', m.time.CLOCK_MONOTONIC, create=True):
                r = c.sample()
            self.assertEqual(r['settings'], {'brightness': '9'})
            self.assertEqual(r['processes']['123']['ticks'], 25)
            self.assertEqual(r['processes']['123']['comm'], 'worker (x)')
            self.assertEqual(r['processes']['123']['service'], 'test.service')
            self.assertNotIn('SECRET', json.dumps(c.metadata()))

    def test_collector_reads_shared_and_local_policy_parameters(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            def put(p, text):
                p = root/p; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
            policy = 'sys/devices/system/cpu/cpufreq/policy0/'
            put(policy+'scaling_governor', 'ondemand')
            put('sys/devices/system/cpu/cpufreq/ondemand/sampling_rate', '8000')
            put('sys/devices/system/cpu/cpufreq/ondemand/up_threshold', '95')
            gpu = 'sys/class/devfreq/fde60000.gpu/'
            put(gpu+'governor', 'simple_ondemand'); put(gpu+'min_freq', '400000000')
            put(gpu+'max_freq', '800000000'); put(gpu+'polling_interval', '100')
            # Never collect arbitrary files from a policy directory.
            put('sys/devices/system/cpu/cpufreq/ondemand/private', 'SECRET')
            with patch.object(m.time, 'CLOCK_BOOTTIME', m.time.CLOCK_MONOTONIC, create=True):
                c = m.Collector(root); r = c.sample()
                self.assertEqual(r['cpu_governor_tunables']['policy0']['sampling_rate'], 8000)
                self.assertEqual(r['gpu_policy']['fde60000.gpu']['polling_interval'], 100)
                self.assertNotIn('SECRET', json.dumps(r))
                put(policy+'ondemand/sampling_rate', '20000')
                self.assertEqual(c.sample()['cpu_governor_tunables']['policy0']['sampling_rate'], 20000)

    def test_recorder_flushes_interruption_and_restores_handlers(self):
        meta, rows = capture()
        with tempfile.TemporaryDirectory() as d:
            args = SimpleNamespace(output=str(Path(d)/'run'), interval=15, duration=60,
                                   warmup=0, mode='shelf', workload='shelf', allow_charging=False)
            before = m.signal.getsignal(m.signal.SIGTERM)
            with patch.object(m.Collector, 'metadata', return_value=meta), \
                 patch.object(m.Collector, 'sample', side_effect=rows[:2]), \
                 patch.object(m.time, 'sleep', side_effect=[None, m.StopCapture()]):
                m.record(args)
            summary = json.loads((Path(args.output)/'summary.json').read_text())
            self.assertEqual(summary['metadata']['stop_reason'], 'interrupted')
            self.assertEqual(summary['samples'], 2)
            self.assertEqual(m.signal.getsignal(m.signal.SIGTERM), before)
            self.assertEqual(len(m.load_capture(Path(args.output)/'samples.jsonl')[1]), 2)

    def test_recorder_stops_on_charger_and_low_charge(self):
        for kind in ('charger_connected', 'low_battery'):
            meta, rows = capture()
            if kind == 'charger_connected':
                rows[1]['supplies']['charger']['online'] = '1'
            else:
                rows[1]['supplies']['battery']['capacity'] = '15'
            with tempfile.TemporaryDirectory() as d:
                args = SimpleNamespace(output=str(Path(d)/'run'), interval=15, duration=60,
                    warmup=0, mode='shelf', workload='shelf', allow_charging=False)
                with patch.object(m.Collector, 'metadata', return_value=meta), \
                     patch.object(m.Collector, 'sample', side_effect=rows[:2]), \
                     patch.object(m.time, 'sleep'):
                    m.record(args)
                summary = json.loads((Path(args.output)/'summary.json').read_text())
                self.assertEqual(summary['metadata']['stop_reason'], kind)


if __name__ == '__main__': unittest.main()
