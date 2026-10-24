#!/usr/bin/env python3
"""Regression tests for boot accounting and checked hardware instrumentation."""
import sys
sys.dont_write_bytecode = True
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'ports/rg353v/rocknix/slot-bootsplash'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


m = load('boot_profile', PKG / 'scripts/slot-boot-profile')
p = load('profile_autostart', PKG / 'tools/patch-autostart.py')


class ProfilerTests(unittest.TestCase):
    def report(self):
        report = {'schema': 1, 'boot_id': '00000000-0000-0000-0000-000000000001',
                  'manager': {'UserspaceTimestampMonotonic': '3000000'}, 'init_entry_s': 1.,
                  'frontend_marks': {'start': 16., 'surface': 17., 'first-frame': 20.},
                  'begin_marks': {'init-mount_storage': 1.5}, 'end_marks': {'init-mount_storage': 2.},
                  'units': [{'Id': 'slot-rg353v.service', 'ExecMainStartTimestampMonotonic': '15000000'},
                            {'Id': 'wifi-recovery.service', 'InactiveExitTimestampMonotonic': '10000000', 'ActiveEnterTimestampMonotonic': '30000000'},
                            {'Id': 'parallel.service', 'InactiveExitTimestampMonotonic': '10000000', 'ActiveEnterTimestampMonotonic': '12000000'}]}
        report['summary'] = m.summarize(report)
        return report

    def test_non_overlapping_stages_cover_only_kernel_to_first_scene(self):
        summary = self.report()['summary']
        self.assertEqual(summary['first_scene_swap_s'], 20.)
        self.assertEqual([x['duration_s'] for x in summary['stages']], [1., 2., 12., 1., 4.])
        self.assertEqual(sum(x['duration_s'] for x in summary['stages']), 20.)
        self.assertTrue(next(x for x in summary['units'] if x['Id'] == 'wifi-recovery.service')['after_shelf'])
        self.assertFalse(next(x for x in summary['units'] if x['Id'] == 'parallel.service')['after_shelf'])

    def test_root_mount_name_cannot_be_parsed_as_a_systemctl_flag(self):
        cmd = m.unit_command(['-.mount', 'slot-rg353v.service'])
        boundary = cmd.index('--')
        self.assertEqual(cmd[boundary+1:], ['-.mount', 'slot-rg353v.service'])
        self.assertTrue(all(p in cmd[:boundary] for p in m.PROPERTIES))

    def test_incomplete_boot_is_not_zero_or_fabricated(self):
        report = self.report()
        report['frontend_marks'] = {}
        report['init_entry_s'] = None
        summary = m.summarize(report)
        self.assertIsNone(summary['first_scene_swap_s'])
        self.assertTrue(all(row['duration_s'] is None for row in summary['stages'][:2]))
        self.assertIsNone(summary['stages'][-1]['duration_s'])

    def test_splash_endpoint_is_separate_from_shelf_and_optional_for_old_reports(self):
        report = self.report()
        self.assertIsNone(report['summary']['first_splash_frame_s'])
        report['end_marks']['splash-first-frame'] = 1.125
        report['summary'] = m.summarize(report)
        self.assertEqual(report['summary']['first_splash_frame_s'], 1.125)
        self.assertEqual(report['summary']['first_scene_swap_s'], 20.)
        self.assertIn('first splash framebuffer write: 1.125 s', m.markdown(report))

    def test_invalid_clocks_and_missing_or_reversed_ends(self):
        for value in ('nan', 'inf', '-1', 'junk', '0', '86401'):
            self.assertIsNone(m.seconds(value))
        self.assertEqual(m.seconds('1.250000000\n'), 1.25)
        rows = m.intervals({'a': 2., 'b': 1.}, {'a': 1., 'c': 3.})
        self.assertTrue(all(row['duration_s'] is None for row in rows))
        row = m.unit_timeline([{'Id': 'restarted.service', 'InactiveExitTimestampMonotonic': '20000000', 'ActiveEnterTimestampMonotonic': '10000000'}], 15.)[0]
        self.assertIsNone(row['end_s'])

    def test_spans_and_frontend_are_in_time_order(self):
        self.assertEqual([x['duration_s'] for x in m.frontend_intervals({'first-frame': 9., 'start': 5., 'surface': 7.})], [2., 2.])
        self.assertEqual(m.intervals({'x': 1.}, {'x': 2.})[0]['duration_s'], 1.)

    def test_capture_is_rejected_before_first_frame(self):
        old = m.ROOT
        with tempfile.TemporaryDirectory() as folder:
            m.ROOT = Path(folder)
            try:
                with self.assertRaisesRegex(RuntimeError, 'refusing'):
                    m.capture()
            finally:
                m.ROOT = old

    def test_first_scene_snapshot_is_saved_before_waiting_for_background_jobs(self):
        report = self.report()
        report['manager']['FinishTimestampMonotonic'] = '0'
        events = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'frontend.displayed').touch()
            with patch.object(m, 'ROOT', root), patch.object(m, 'collect_once', return_value=report), patch.object(m, 'store', side_effect=lambda *a, **k: events.append('stored')), patch.object(m.time, 'sleep', side_effect=RuntimeError('interrupted before background completion')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    m.capture()
        self.assertEqual(events, ['stored'])

    def test_retention_exports_and_repeat_same_boot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for i in range(12):
                report = self.report()
                report['boot_id'] = f'00000000-0000-0000-0000-{i:012d}'
                m.store(report, root, '<svg/>')
            self.assertEqual(len(list(root.glob('*.json'))), m.KEEP)
            self.assertEqual(len(list(root.glob('*.md'))), m.KEEP)
            self.assertEqual(len(list(root.glob('*.csv'))), m.KEEP)
            self.assertEqual(len(list(root.glob('*.svg'))), m.KEEP)
            m.store(report, root)
            self.assertEqual(len(list(root.glob('*.json'))), m.KEEP)
            parsed = json.loads((root / ('boot-' + report['boot_id'] + '.json')).read_text())
            self.assertEqual(parsed['summary']['first_scene_swap_s'], 20.)
            self.assertIn('unmeasured', m.markdown(report))
            report['boot_id'] = '../bad'
            with self.assertRaises(ValueError):
                m.store(report, root)

    def test_autostart_checks_every_official_invocation_and_is_idempotent(self):
        text = '\n'.join(['  "${script}" 2>&1 >>${BOOTLOG}'] * 3 + ['  ${script} 2>&1 >>${BOOTLOG}'] * 2) + '\n'
        patched = p.patch(text)
        self.assertEqual(p.patch(patched), patched)
        self.assertEqual(patched.count('--begin "hardware-'), 5)
        self.assertIn('hardware-custom-${script##*/}', patched)
        with self.assertRaisesRegex(ValueError, 'invocations changed'):
            p.patch(text.replace('  ${script} 2>&1 >>${BOOTLOG}\n', '', 1))


if __name__ == '__main__':
    unittest.main()
