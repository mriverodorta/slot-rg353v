#!/usr/bin/env python3
"""Execute the fixed hardware operations against isolated fake sysfs/settings."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'ports/rg353v/rocknix/slot-startup-profile/scripts/slot-hardware-start'


class Hardware(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'system.cfg'
        self.config.write_text('system.hostname=slot\ndisplay.brightness=50\nsystem.suspendmode=mem\n')
        for name, value in {
            'devices/system/cpu/cpufreq/policy0/scaling_governor': 'ondemand',
            'class/backlight/backlight/max_brightness': '255',
            'class/backlight/backlight/brightness': '0',
            'devices/system/cpu/cpu1/online': '0',
            'devices/system/cpu/cpu2/online': '0',
            'devices/system/cpu/cpu3/online': '0',
            'gpu/governor': 'ondemand', 'gpu/min_freq': '0',
        }.items():
            path = self.root / 'sys' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value + '\n')
        text = SOURCE.read_text()
        self.script = text[text.index('declare -A settings=()'):text.index('configure_rumble()')]
        self.script = self.script.replace('/sys/', str(self.root / 'sys') + '/')
        self.script = self.script.replace('/dev/mali0', str(self.root / 'mali0'))
        self.script = self.script.replace('/usr/lib/autostart/common/008-perfmode', 'echo legacy-threads')
        self.script = self.script.replace('/usr/lib/autostart/common/009-sleepmode', 'echo legacy-sleep')
        self.script = f'J_CONF="{self.config}"\nGPU_FREQ="{self.root}/sys/gpu"\n' + self.script

    def run_ops(self, ops):
        result = subprocess.run(['bash', '-e', '-c', self.script + '\nload_settings\n' + ops],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_precedence_duplicates_and_values_are_not_evaluated(self):
        marker = self.root / 'should-not-exist'
        self.config.write_text(f'global.x=g\nx=l\nsystem.x=s\nsystem.x=duplicate\nz=$(touch {marker})\n')
        self.assertEqual(self.run_ops('get_setting x; get_setting z'), f's\n$(touch {marker})')
        self.assertFalse(marker.exists())

    def test_empty_precedence_falls_back_without_losing_equals_in_value(self):
        self.config.write_text('system.x=\nx=a=b\nglobal.x=g\n')
        self.assertEqual(self.run_ops('get_setting x'), 'a=b')

    def test_brightness_clamps_and_maps_to_fixed_backlight(self):
        for setting, expected in [('50', 127), ('0', 25), ('005', 12), ('100', 255), ('200', 255), ('bad', 25), ('18446744073709551615', 25)]:
            self.config.write_text('display.brightness=' + setting + '\n')
            self.run_ops('configure_display')
            self.assertEqual((self.root / 'sys/class/backlight/backlight/brightness').read_text().strip(), str(expected))

    def test_gpu_load_is_skipped_only_when_module_and_character_device_are_ready(self):
        operation = 'modprobe() { printf "load:%s" "$1"; }; configure_gpu_driver'
        self.assertEqual(self.run_ops(operation), 'load:mali_kbase')
        (self.root / 'sys/module/mali_kbase').mkdir(parents=True)
        self.assertEqual(self.run_ops(operation), 'load:mali_kbase')
        node = self.root / 'mali0'
        node.touch()  # A stale regular file must never certify a working GPU.
        self.assertEqual(self.run_ops(operation), 'load:mali_kbase')
        node.unlink()
        node.symlink_to('/dev/null')  # Isolated character-device fixture.
        self.assertEqual(self.run_ops(operation), '')
        (self.root / 'sys/module/mali_kbase').rmdir()
        self.assertEqual(self.run_ops(operation), 'load:mali_kbase')

    def test_fixed_gpu_policy_does_not_search_for_governors(self):
        for requested, expected in [('auto', 'simple_ondemand'), ('default', 'simple_ondemand'), ('performance', 'performance'), ('powersave', 'powersave')]:
            self.run_ops('set_gpu ' + requested)
            self.assertEqual((self.root / 'sys/gpu/governor').read_text().strip(), expected)

    def test_persisted_sleep_does_not_restart_logind(self):
        self.assertEqual(self.run_ops('configure_sleep'), '')

    def test_all_cores_are_online_and_explicit_policy_is_fixed_to_four_cores(self):
        self.run_ops('configure_performance')
        for core in range(1, 4):
            self.assertEqual((self.root / f'sys/devices/system/cpu/cpu{core}/online').read_text(), '1\n')
        self.config.write_text('system.threads=2\n')
        self.run_ops('configure_performance')
        for core in range(1, 4):
            self.assertEqual((self.root / f'sys/devices/system/cpu/cpu{core}/online').read_text(), ('1' if core < 2 else '0') + '\n')


if __name__ == '__main__':
    unittest.main()
