#!/usr/bin/env python3
"""Offline safety and failure-path checks for the device-specific probe recovery."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('wifi_probe', str(ROOT / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-wifi-probe-recovery'))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.sysfs = root / 'sys'
        self.runtime = root / 'run'
        self.runtime.mkdir()
        self.compat = self.sysfs / 'firmware/devicetree/base/compatible'
        self.compat.parent.mkdir(parents=True)
        self.compat.write_bytes(b'anbernic,rg353v\0rockchip,rk3566\0')
        self.driver = self.sysfs / 'bus/platform/drivers/dwmmc_rockchip'
        self.driver.mkdir(parents=True)
        for name in ['bind', 'unbind']:
            (self.driver / name).write_text('')
        self.controller = self.sysfs / 'bus/platform/devices/fe000000.mmc'
        self.dev = self.controller / 'mmc_host/mmc7/mmc7:0001/mmc7:0001:1'
        self.dev.mkdir(parents=True)
        (self.controller / 'driver').symlink_to(self.driver)
        (self.dev / 'vendor').write_text('0x024c\n')
        (self.dev / 'device').write_text('0xc821\n')
        self.chip_driver = self.sysfs / 'bus/sdio/drivers/rtw88_8821cs'
        self.chip_driver.mkdir(parents=True)
        self.signature = 'rtw88_8821cs mmc7:0001:1: probe with driver rtw88_8821cs failed with error -110'
        self.kernel = self.signature
        self.radio = 'enabled'
        self.radio_reads = 0
        self.recover_on_bind = True
        self.sleeps = []
        self.log = []
        self.commands = []
        self.recovery = m.Recovery(self.sysfs, self.runtime, self.execute, self.sleep)

    def execute(self, args):
        self.commands.append(args)
        if args[0] == 'nmcli':
            self.radio_reads += 1
            return subprocess.CompletedProcess(args, 0, self.radio+'\n', '')
        return subprocess.CompletedProcess(args, 0, self.kernel, '')

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if (self.driver / 'unbind').read_text():
            (self.controller / 'driver').unlink(missing_ok=True)
        if (self.driver / 'bind').read_text() and self.recover_on_bind:
            if not (self.controller / 'driver').exists():
                (self.controller / 'driver').symlink_to(self.driver)
            self.bind_adapter()

    def bind_adapter(self):
        if not (self.dev / 'driver').exists():
            (self.dev / 'driver').symlink_to(self.chip_driver)
        (self.dev / 'net/wlan0').mkdir(parents=True, exist_ok=True)

    def run_recovery(self):
        return self.recovery.recover(self.log.append)

    def untouched(self):
        self.assertEqual((self.driver / 'unbind').read_text(), '')
        self.assertFalse(self.recovery.marker.exists())

    def test_actual_failed_signature_triggers_one_controller_reset(self):
        self.assertTrue(self.run_recovery())
        self.assertEqual((self.driver / 'unbind').read_text(), 'fe000000.mmc')
        self.assertEqual((self.driver / 'bind').read_text(), 'fe000000.mmc')
        self.assertFalse(self.run_recovery())
        self.assertEqual(self.sleeps, [2, 2])
        self.assertTrue((self.dev / 'driver').exists())

    def test_bound_adapter_never_reset_even_with_old_failure_in_journal(self):
        self.bind_adapter()
        self.assertFalse(self.run_recovery())
        self.untouched()

    def test_existing_interface_without_driver_is_not_reset(self):
        (self.dev / 'net/wlan0').mkdir(parents=True)
        self.assertFalse(self.run_recovery())
        self.untouched()

    def test_radio_off_is_respected(self):
        self.radio = 'disabled'
        self.assertFalse(self.run_recovery())
        self.untouched()

    def test_radio_changed_while_collecting_evidence_is_respected(self):
        execute = self.execute
        def changed(args):
            result = execute(args)
            if args[0] == 'journalctl':
                self.radio = 'disabled'
            return result
        self.recovery.execute = changed
        self.assertFalse(self.run_recovery())
        self.untouched()

    def test_network_tool_failure_does_not_enable_or_reset_radio(self):
        self.recovery.execute = lambda args: subprocess.CompletedProcess(args, 1, '', '')
        self.assertFalse(self.run_recovery())
        self.untouched()

    def test_tool_timeout_is_safe(self):
        def timeout(args):
            raise subprocess.TimeoutExpired(args, 10)
        self.recovery.execute = timeout
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_recovery()
        self.untouched()

    def test_empty_and_unrelated_kernel_errors_are_not_enough(self):
        for kernel in ['', self.signature.replace('mmc7:', 'mmc8:'), self.signature.replace('-110', '-5'), 'failed to download firmware']:
            self.kernel = kernel
            self.assertFalse(self.run_recovery())
            self.untouched()

    def test_other_model_or_prefix_match_is_rejected(self):
        for compatible in [b'anbernic,rg353vs\0', b'anbernic,rg353v-extra\0']:
            self.compat.write_bytes(compatible)
            with self.assertRaises(ValueError):
                self.run_recovery()
            self.untouched()

    def test_other_chip_is_rejected(self):
        (self.dev / 'device').write_text('0x1234')
        with self.assertRaises(ValueError):
            self.run_recovery()
        self.untouched()

    def test_storage_controller_is_rejected(self):
        (self.dev.parent / 'block/mmcblk9').mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.run_recovery()
        self.untouched()

    def test_multiple_functions_are_rejected(self):
        other = self.dev.parent / 'mmc7:0001:2'
        other.mkdir()
        with self.assertRaises(ValueError):
            self.run_recovery()
        self.untouched()

    def test_controller_already_detached_is_left_untouched(self):
        (self.controller / 'driver').unlink()
        self.assertFalse(self.run_recovery())
        self.untouched()

    def test_failed_recovery_is_bounded_and_not_repeated(self):
        self.recover_on_bind = False
        self.assertFalse(self.run_recovery())
        self.assertEqual(len(self.sleeps), 16)
        self.assertFalse(self.run_recovery())
        self.assertEqual(len(self.sleeps), 16)
        self.assertTrue(any('no more automatic resets' in x for x in self.log))

    def test_interruption_after_detach_rebinds_in_finally(self):
        def interrupted(seconds):
            (self.controller / 'driver').unlink()
            raise RuntimeError('interrupted')
        self.recovery.sleep = interrupted
        with self.assertRaises(RuntimeError):
            self.run_recovery()
        self.assertEqual((self.driver / 'bind').read_text(), 'fe000000.mmc')

    def test_stop_hook_requires_attempt_marker_and_exact_hardware(self):
        (self.controller / 'driver').unlink()
        self.recovery.restore()
        self.assertEqual((self.driver / 'bind').read_text(), '')
        self.recovery.marker.write_text('fe2b0000.mmc')
        self.recovery.restore()
        self.assertEqual((self.driver / 'bind').read_text(), '')
        self.recovery.marker.write_text('fe000000.mmc')
        self.recovery.restore()
        self.assertEqual((self.driver / 'bind').read_text(), 'fe000000.mmc')

    def test_driver_retry_restores_adapter_without_resetting_host(self):
        bind = self.chip_driver / 'bind'; bind.write_text('')
        def ready(seconds):
            self.sleeps.append(seconds)
            if bind.read_text(): self.bind_adapter()
        self.recovery.sleep = ready
        self.assertTrue(self.recovery.retry_driver(self.log.append))
        self.assertEqual(bind.read_text(), self.dev.name)
        self.assertTrue(self.recovery.driver_marker.exists())
        self.assertEqual((self.driver / 'unbind').read_text(), '')
        self.assertFalse(self.recovery.retry_driver(self.log.append))
        self.assertEqual(self.sleeps, [2])

    def test_driver_retry_requires_exact_failure_and_enabled_radio(self):
        bind = self.chip_driver / 'bind'; bind.write_text('')
        for kernel, radio in [('', 'enabled'), (self.signature, 'disabled')]:
            self.kernel, self.radio = kernel, radio
            self.assertFalse(self.recovery.retry_driver(self.log.append))
            self.assertFalse(self.recovery.driver_marker.exists())
            self.assertEqual(bind.read_text(), '')

    def test_driver_retry_rejects_a_storage_controller(self):
        (self.chip_driver / 'bind').write_text('')
        (self.dev.parent / 'block/mmcblk8').mkdir(parents=True)
        with self.assertRaises(ValueError): self.recovery.retry_driver(self.log.append)
        self.assertFalse(self.recovery.driver_marker.exists())

    def test_failed_driver_retry_is_bounded_and_not_repeated(self):
        (self.chip_driver / 'bind').write_text('')
        self.recovery.sleep = lambda seconds: self.sleeps.append(seconds)
        self.assertFalse(self.recovery.retry_driver(self.log.append))
        self.assertEqual(self.sleeps, [2]*5)
        self.assertFalse(self.recovery.retry_driver(self.log.append))
        self.assertEqual(self.sleeps, [2]*5)
        self.assertEqual((self.driver / 'unbind').read_text(), '')

    def test_driver_retry_stops_when_user_turns_radio_off(self):
        (self.chip_driver / 'bind').write_text('')
        def disabled(seconds): self.sleeps.append(seconds); self.radio = 'disabled'
        self.recovery.sleep = disabled
        self.assertFalse(self.recovery.retry_driver(self.log.append))
        self.assertEqual(self.sleeps, [2])

    def test_driver_retry_does_not_touch_a_working_adapter(self):
        bind = self.chip_driver / 'bind'; bind.write_text(''); self.bind_adapter()
        self.assertFalse(self.recovery.retry_driver(self.log.append))
        self.assertEqual(bind.read_text(), '')
        self.assertFalse(self.recovery.driver_marker.exists())

    def test_driver_retry_rejects_other_chip(self):
        (self.chip_driver / 'bind').write_text(''); (self.dev / 'device').write_text('0x1234')
        with self.assertRaises(ValueError): self.recovery.retry_driver(self.log.append)
        self.assertFalse(self.recovery.driver_marker.exists())

    def test_driver_retry_handles_probe_io_error_without_reset_loop(self):
        bind = self.chip_driver / 'bind'; bind.write_text('')
        self.recovery.sleep = lambda seconds: self.sleeps.append(seconds)
        original = Path.write_text
        def failed(path, text, *args, **kwargs):
            if path == bind: raise OSError('probe failed')
            return original(path, text, *args, **kwargs)
        from unittest.mock import patch
        with patch.object(Path, 'write_text', failed):
            self.assertFalse(self.recovery.retry_driver(self.log.append))
        self.assertTrue(self.recovery.driver_marker.exists())
        self.assertEqual(self.sleeps, [2]*5)


if __name__ == '__main__':
    unittest.main()
