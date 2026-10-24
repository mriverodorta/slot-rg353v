#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / 'ports/rg353v/bootloader/read-bootstage.py'
spec = importlib.util.spec_from_file_location('bootstage', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BootstageTests(unittest.TestCase):
    def report(self, values):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'name').write_bytes(b'bootstage\0')
            for i, (name, kind, us) in enumerate(reversed(values)):
                node = root / str(i)
                node.mkdir()
                (node / 'name').write_bytes(name.encode() + b'\0')
                (node / kind).write_bytes(struct.pack('>I', us))
            return module.read_report(root, 'test-boot')

    def test_synthetic_origin_and_overlapping_accumulator_are_not_durations(self):
        result = self.report([('reset', 'mark', 0), ('SPL', 'mark', 500000),
                              ('dm', 'accum', 12000), ('slot-panel-start', 'mark', 700000),
                              ('slot-panel-end', 'mark', 740000)])
        self.assertTrue(result['monotonic_marks'])
        self.assertTrue(result['records'][0]['synthetic_origin'])
        self.assertEqual([s['duration_us'] for s in result['operation_spans']], [40000])

    def test_repeated_file_reads_remain_separate(self):
        result = self.report([('/KERNEL', 'mark', 5), ('slot-file-read-start', 'mark', 6),
                              ('slot-file-read-end', 'mark', 30), ('/device_trees/panel.dtb', 'mark', 31),
                              ('slot-file-read-start', 'mark', 32), ('slot-file-read-end', 'mark', 37)])
        self.assertEqual([(s['file'], s['duration_us']) for s in result['operation_spans']],
                         [('/KERNEL', 24), ('/device_trees/panel.dtb', 5)])

    def test_clock_discontinuity_is_reported(self):
        self.assertFalse(self.report([('SPL', 'mark', 3000), ('board_init_f', 'mark', 1000)])['monotonic_marks'])

    def test_backward_operation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'backwards'):
            self.report([('slot-panel-start', 'mark', 2000), ('slot-panel-end', 'mark', 1000)])

    def test_missing_export_is_explicit(self):
        with self.assertRaisesRegex(ValueError, 'No BOOTSTAGE'):
            module.read_report(Path('/nonexistent-bootstage-export'), 'test')

    def test_incomplete_fdt_export_cannot_silently_drop_a_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root / '0'
            node.mkdir()
            (node / 'name').write_bytes(b'SPL\0')
            with self.assertRaisesRegex(ValueError, 'expected one timing field'):
                module.read_report(root, 'test')

    def sd_marker(self, **overrides):
        values = dict(phase='before', controller='fe2b0000.mmc', mode='SD High Speed (50MHz)',
                      bus_width=4, requested_hz=50000000, provider_hz=50000000,
                      fixed_divider=2, divider=0, ctype=1, signal_voltage_enum=4, fifo_mode=0,
                      dma64=0, ddr=0, config_max_hz=150000000, max_blocks=65535,
                      card_caps=13, host_caps=13)
        values.update(overrides)
        return 'slot-sd-probe;' + ';'.join(f'{k}={v}' for k, v in values.items())

    def test_live_sd_metadata_keeps_mode_and_clock_quantization(self):
        result = self.report([(self.sd_marker(requested_hz=25000000, provider_hz=24000000), 'mark', 100)])
        row = result['sd_snapshots'][0]
        self.assertEqual(row['mode'], 'SD High Speed (50MHz)')
        self.assertEqual(row['card_clock_hz_derived'], 12000000)
        self.assertEqual(row['requested_hz'], 25000000)
        self.assertEqual(row['transfer_path'], 'IDMAC DMA')

    def test_divider_and_fifo_path_are_explicit(self):
        row = self.report([(self.sd_marker(divider=2, fifo_mode=1), 'mark', 100)])['sd_snapshots'][0]
        self.assertEqual(row['card_clock_hz_derived'], 6250000)
        self.assertEqual(row['transfer_path'], 'FIFO / PIO')

    def test_clock_provider_error_cannot_be_reported_as_a_high_clock(self):
        with self.assertRaisesRegex(ValueError, 'clock provider'):
            self.report([(self.sd_marker(provider_hz=2**64-22), 'mark', 100)])

    def test_rk3566_fixed_divider_matches_the_measured_bandwidth_ceiling(self):
        row = self.report([(self.sd_marker(), 'mark', 100)])['sd_snapshots'][0]
        self.assertEqual(row['requested_hz'], 50000000)
        self.assertEqual(row['card_clock_hz_derived'], 25000000)
        self.assertEqual(row['theoretical_payload_MB_s'], 12.5)


if __name__ == '__main__':
    unittest.main()
