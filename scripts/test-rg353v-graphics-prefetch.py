#!/usr/bin/env python3
"""Optional graphics cache hints: identity, bounds, fallback and image policy."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'ports/rg353v/rocknix/slot-startup-profile'
spec = importlib.util.spec_from_file_location('startup', PKG / 'tools/configure-startup.py')
compose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compose)


def pin(data):
    value = 14695981039346656037
    for byte in data[:4096]:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f'{value:016x}'


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'usr/share/slot/hardware'
        self.folder.mkdir(parents=True)
        self.link = self.root / 'usr/lib/systemd/system/sysinit.target.wants/slot-graphics-prefetch.service'

    def fixture(self):
        names = ['/usr/lib/libgbm.so.1', '/usr/lib/libmali.so.1', '/usr/lib/libSDL2-2.0.so.0']
        lines = ['SLOT-PREFETCH-1 4096']
        libraries = {}
        for i, name in enumerate(names):
            data = bytes([i + 1]) * 8192
            p = self.root / name.lstrip('/')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            libraries[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            lines.extend([f'FILE {name} {len(data)} {pin(data)}', 'RANGE 0 4096', 'END'])
        self.meta = {'schema': 1, 'page_bytes': 4096, 'libraries': libraries}
        self.write('\n'.join(lines) + '\n')

    def write(self, text):
        (self.folder / 'graphics-pages.list').write_text(text)
        self.meta['profile_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        (self.folder / 'graphics-pages.json').write_text(json.dumps(self.meta))

    def test_exact_libraries_enable_only_optional_sysinit_unit(self):
        self.fixture()
        self.assertTrue(compose.graphics_prefetch(self.root)['enabled'])
        self.assertEqual(self.link.readlink(), Path('../slot-graphics-prefetch.service'))
        text = (PKG / 'system.d/slot-graphics-prefetch.service').read_text()
        self.assertIn('DefaultDependencies=no', text)
        self.assertNotIn('slot-rg353v', text)
        self.assertIn('IOSchedulingClass=idle', text)
        self.assertIn('TimeoutStartSec=5', text)

    def test_changed_library_disables_hints_without_blocking_image(self):
        self.fixture()
        compose.graphics_prefetch(self.root)
        (self.root / 'usr/lib/libmali.so.1').write_bytes(b'new version')
        self.assertEqual(compose.graphics_prefetch(self.root)['reason'], 'library-mismatch')
        self.assertFalse(self.link.exists())

    def test_missing_profile_is_a_supported_fallback(self):
        self.assertEqual(compose.graphics_prefetch(self.root)['reason'], 'no-profile')
        self.assertFalse(self.link.exists())

    def test_invalid_hash_and_out_of_bounds_range_stop_composition(self):
        self.fixture()
        p = self.folder / 'graphics-pages.list'
        old = p.read_text()
        p.write_text(old + 'bad\n')
        with self.assertRaises(ValueError):
            compose.graphics_prefetch(self.root)
        self.write(old.replace('RANGE 0 4096', 'RANGE 12288 4096', 1))
        with self.assertRaises(ValueError):
            compose.graphics_prefetch(self.root)

    def test_wrong_header_pin_stops_composition(self):
        self.fixture()
        p = self.folder / 'graphics-pages.list'
        self.write(p.read_text().replace(pin(bytes([1]) * 8192), '0' * 16))
        with self.assertRaisesRegex(ValueError, 'header pin'):
            compose.graphics_prefetch(self.root)

    def test_absolute_image_symlink_stays_inside_image(self):
        self.fixture()
        p = self.root / 'usr/lib/libmali.so.1'
        data = p.read_bytes()
        p.unlink()
        target = self.root / 'usr/lib/mali-real.so'
        target.write_bytes(data)
        p.symlink_to('/usr/lib/mali-real.so')
        self.assertTrue(compose.graphics_prefetch(self.root)['enabled'])


@unittest.skipUnless(sys.platform == 'linux', 'native fadvise tests run in the Linux build container')
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.binary = cls.root / 'prefetch'
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(PKG / 'src/slot-graphics-prefetch.c'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.data = self.root / 'library'
        self.data.write_bytes(b'x' * 8192)
        self.profile = self.root / 'profile'
        self.profile.write_text(f'SLOT-PREFETCH-1 4096\nFILE {self.data} 8192 {pin(self.data.read_bytes())}\nRANGE 0 4096\nEND\n')

    def run_hint(self):
        p = subprocess.run([str(self.binary), str(self.profile)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        return p.stderr

    def test_valid_profile_advises_expected_range(self):
        self.assertIn('1 matched, 1 ranges, 4 KiB advised', self.run_hint())

    def test_replaced_or_missing_library_is_skipped(self):
        self.data.write_bytes(b'y' * 8192)
        self.assertIn('0 matched, 1 ranges, 0 KiB advised', self.run_hint())
        self.data.unlink()
        self.assertIn('0 matched, 1 ranges, 0 KiB advised', self.run_hint())

    def test_bad_header_has_no_advice(self):
        self.profile.write_text('SLOT-PREFETCH-1 16384\n')
        self.assertEqual(self.run_hint(), '')

    def test_overflow_and_unaligned_ranges_stop(self):
        for value in ('RANGE 18446744073709551615 4096', 'RANGE 1 4096'):
            self.setUp()
            self.profile.write_text(self.profile.read_text().replace('RANGE 0 4096', value))
            self.assertIn('stopped', self.run_hint())

    def test_incomplete_profile_stops_without_failure(self):
        self.profile.write_text(self.profile.read_text().replace('END\n', ''))
        self.assertIn('stopped', self.run_hint())

    def test_advice_budget_is_bounded(self):
        size = 64 << 20
        with self.data.open('r+b') as stream:
            stream.truncate(size)
        self.profile.write_text(f'SLOT-PREFETCH-1 4096\nFILE {self.data} {size} {pin(self.data.read_bytes()[:4096])}\nRANGE 0 {52 << 20}\nEND\n')
        self.assertIn('stopped', self.run_hint())


if __name__ == '__main__':
    unittest.main()
