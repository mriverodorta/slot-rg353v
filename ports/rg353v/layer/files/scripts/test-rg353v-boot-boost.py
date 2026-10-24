#!/usr/bin/env python3
"""Exercise startup CPU restoration against isolated sysfs and boot markers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'ports/rg353v/rocknix/slot-startup-profile'


class Boost(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / 'sys/devices/system/cpu/cpufreq/policy0'
        self.policy.mkdir(parents=True)
        self.governor = self.policy / 'scaling_governor'
        self.governor.write_text('performance\n')
        self.sampling = self.policy.parent / 'ondemand/sampling_rate'
        self.sampling.parent.mkdir()
        self.sampling.write_text('8000\n')
        self.minimum = self.policy / 'scaling_min_freq'
        self.maximum = self.policy / 'scaling_max_freq'
        self.threshold = self.sampling.parent / 'up_threshold'
        self.minimum.write_text('408000\n')
        self.maximum.write_text('1800000\n')
        self.threshold.write_text('95\n')
        self.boot = self.root / 'run/slot-boot'
        self.frame = self.boot / 'frontend/first-frame'
        self.pending = self.boot / 'cpu-governor'
        self.uptime = self.root / 'uptime'
        self.uptime.write_text('4.25 12.50\n')
        text = (PKG / 'scripts/slot-boot-boost').read_text()
        text = text.replace('/sys/', str(self.root / 'sys') + '/')
        text = text.replace('/run/', str(self.root / 'run') + '/')
        text = text.replace('/storage/', str(self.root / 'storage') + '/')
        text = text.replace('/usr/share/', str(self.root / 'usr/share') + '/')
        self.script = text.replace('/proc/uptime', str(self.uptime))

    def test_optional_schedutil_survives_late_boost_release_only_if_installed(self):
        self.governor.parent.joinpath('scaling_available_governors').write_text('ondemand schedutil performance\n')
        state=self.root/'storage/slotcontent/Config/slot.state';state.parent.mkdir(parents=True)
        state.write_text('schedutil_governor=1\n')
        for path in ('usr/share/slot/features-v1','storage/.config/slot/features-v1'):
            p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('slot-features-v1\nschedutil-governor\n')
        self.run_boost('defer','ondemand')
        self.assertEqual(self.governor.read_text(),'performance\n')
        self.run_boost('release')
        self.assertEqual(self.governor.read_text(),'schedutil\n')
        self.assertEqual(self.sampling.read_text(),'8000\n')
        for path in ('usr/share/slot/features-v1','storage/.config/slot/features-v1'):
            (self.root/path).write_text('slot-features-v1\n')
            self.run_boost('defer','ondemand');self.run_boost('release')
            self.assertEqual(self.governor.read_text(),'ondemand\n')
            (self.root/path).write_text('slot-features-v1\nschedutil-governor\n')
        (self.root/'storage/.config/slot/features-v1').write_text('invalid-header\nschedutil-governor\n')
        self.run_boost('defer','ondemand');self.run_boost('release')
        self.assertEqual(self.governor.read_text(),'ondemand\n')

    def test_unavailable_optional_governor_preserves_safe_ondemand_fallback(self):
        self.governor.parent.joinpath('scaling_available_governors').write_text('ondemand performance\n')
        state=self.root/'storage/slotcontent/Config/slot.state';state.parent.mkdir(parents=True)
        state.write_text('schedutil_governor=1\n')
        self.run_boost('defer','ondemand');self.run_boost('release')
        self.assertEqual(self.governor.read_text(),'ondemand\n')
        self.assertEqual(self.sampling.read_text(),'20000\n')

    def run_boost(self, *args, ok=True):
        result = subprocess.run(['sh', '-c', self.script, 'boost', *args], capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_boost_ends_at_frame_and_preserves_requested_governor(self):
        for requested in ('ondemand', 'schedutil', 'powersave', 'performance'):
            self.governor.write_text('performance\n')
            self.run_boost('defer', requested)
            self.assertEqual(self.governor.read_text(), 'performance\n')
            self.assertEqual(self.pending.read_text(), requested + '\n')
            self.run_boost('release')
            self.assertEqual(self.governor.read_text(), requested + '\n')
            self.assertFalse(self.pending.exists())
            self.run_boost('release')  # Idempotent after a timer/path race.

    def test_late_or_manual_setup_does_not_leave_boost_pending(self):
        self.frame.parent.mkdir(parents=True)
        self.frame.touch()
        self.run_boost('defer', 'ondemand')
        self.assertEqual(self.governor.read_text(), 'ondemand\n')
        self.assertFalse(self.pending.exists())
        self.frame.unlink()
        for uptime in ('20.00', '100.25'):
            self.uptime.write_text(uptime + ' 12.50\n')
            self.governor.write_text('performance\n')
            self.run_boost('defer', 'powersave')
            self.assertEqual(self.governor.read_text(), 'powersave\n')
            self.assertFalse(self.pending.exists())

    def test_deferred_ondemand_cadence_is_applied_only_when_boot_boost_ends(self):
        self.run_boost('defer', 'ondemand')
        self.assertEqual(self.sampling.read_text(), '8000\n')
        self.run_boost('release')
        self.assertEqual(self.sampling.read_text(), '20000\n')
        self.assertEqual(self.governor.read_text(), 'ondemand\n')
        self.assertEqual(self.minimum.read_text(), '408000\n')
        self.assertEqual(self.maximum.read_text(), '1800000\n')
        self.assertEqual(self.threshold.read_text(), '95\n')

    def test_existing_frame_and_timeout_set_cadence_but_other_governors_do_not(self):
        self.frame.parent.mkdir(parents=True)
        self.frame.touch()
        for requested in ('ondemand', 'schedutil', 'powersave', 'performance'):
            self.sampling.write_text('8000\n')
            self.run_boost('defer', requested)
            expected = '20000\n' if requested == 'ondemand' else '8000\n'
            self.assertEqual(self.sampling.read_text(), expected)
        self.frame.unlink()
        self.uptime.write_text('20.25 12.50\n')
        self.sampling.write_text('8000\n')
        self.run_boost('defer', 'ondemand')
        self.assertEqual(self.sampling.read_text(), '20000\n')

    def test_invalid_policy_cannot_be_written_or_evaluated(self):
        marker = self.root / 'injected'
        for requested in ('invalid', 'ondemand\nperformance', '$(touch ' + str(marker) + ')'):
            self.assertNotEqual(self.run_boost('defer', requested, ok=False).returncode, 0)
            self.assertEqual(self.governor.read_text(), 'performance\n')
        self.assertFalse(marker.exists())
        self.boot.mkdir(parents=True)
        self.pending.write_text('invalid\n')
        self.assertNotEqual(self.run_boost('release', ok=False).returncode, 0)
        self.assertEqual(self.governor.read_text(), 'performance\n')

    def test_frame_racing_publication_restores_policy(self):
        # Emulate a frame becoming visible immediately after atomic publication.
        self.script = self.script.replace('mv -f "$pending.tmp" "$pending"',
            'mv -f "$pending.tmp" "$pending"\nmkdir -p "${frame%/*}"\n: >"$frame"')
        self.run_boost('defer', 'ondemand')
        self.assertEqual(self.governor.read_text(), 'ondemand\n')
        self.assertFalse(self.pending.exists())

    def test_deadline_racing_publication_restores_policy(self):
        self.script = self.script.replace('mv -f "$pending.tmp" "$pending"',
            'mv -f "$pending.tmp" "$pending"\nprintf "20.1 50.0\\n" >' + str(self.uptime))
        self.run_boost('defer', 'ondemand')
        self.assertEqual(self.governor.read_text(), 'ondemand\n')
        self.assertFalse(self.pending.exists())

    def test_existing_first_frame_and_deadline_release_before_background_work(self):
        service = (PKG / 'system.d/slot-background.service').read_text()
        self.assertIn('RemainAfterExit=yes', service)
        self.assertIn('OnBootSec=20s', (PKG / 'system.d/slot-background.timer').read_text())
        self.assertIn('PathExists=/run/slot-boot/frontend/first-frame',
                      (PKG / 'system.d/slot-background.path').read_text())
        script = (PKG / 'scripts/slot-background-start').read_text()
        self.assertLess(script.index('slot-boot-boost release'), script.index('mkdir -p'))


if __name__ == '__main__':
    unittest.main()
