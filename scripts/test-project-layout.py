#!/usr/bin/env python3
"""Offline checks for public/private build separation, ownership and documentation."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock
import json

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


image = load('image_builder', 'build-image.py')
kit = load('kit_builder', 'prepare-rg353v-module-kit.py')


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = image.ROOT
        image.ROOT = Path(self.tmp.name)

    def tearDown(self):
        image.ROOT = self.old_root
        self.tmp.cleanup()

    def args(self, **kw):
        data = dict(profile='release', version='test-1', firmware=None, loader=None,
                    module_kit=None, lock=ROOT/'ports/rg353v/upstreams.lock.json')
        data.update(kw)
        return argparse.Namespace(**data)

    def test_public_plan_needs_no_private_directory(self):
        plan = image.plan(self.args())
        self.assertTrue(plan['source_build'])
        self.assertFalse(plan['private'])
        self.assertEqual(Path(plan['output']), image.ROOT/'release/test-1')

    def test_development_requires_own_provisioning(self):
        with self.assertRaisesRegex(ValueError, 'Configure localdev'):
            image.plan(self.args(profile='localdev'))
        p = image.ROOT/'localdev/provisioning'
        p.mkdir(parents=True)
        for name in ('slot-setup-debug.json', 'ssh_host_ed25519_key'):
            (p/name).write_text('fixture')
        self.assertTrue(image.plan(self.args(profile='localdev'))['private'])

    def test_public_refuses_private_input_even_through_symlink(self):
        p = image.ROOT/'localdev/firmware.img.gz'
        p.parent.mkdir()
        p.write_bytes(b'fixture')
        alias = image.ROOT/'firmware.img.gz'
        alias.symlink_to(p)
        with self.assertRaisesRegex(ValueError, 'refuse localdev'):
            image.plan(self.args(firmware=alias, loader=p, module_kit=p))

    def test_partial_fast_inputs_and_overwrite_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'together'):
            image.plan(self.args(loader=Path('/unused')))
        p = image.ROOT/'release/test-1'
        p.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            image.plan(self.args())

    def test_output_cannot_escape_version_directory(self):
        for value in ('../private', '/tmp/a', 'a/b', 'name;command', ''):
            with self.assertRaises(ValueError):
                image.plan(self.args(version=value))

    def test_package_ownership_uses_actual_package_files(self):
        p = image.ROOT/'packages'
        (p/'openssh-9.8p1/usr/sbin').mkdir(parents=True)
        (p/'openssh-9.8p1/usr/sbin/sshd').write_text('elf fixture')
        (p/'openssh-extra-1/usr/bin').mkdir(parents=True)
        (p/'openssh-extra-1/usr/bin/unrelated').write_text('fixture')
        value = kit.owners(p, {'modules': [{'id': 'ssh', 'packages': ['openssh']}]})
        self.assertEqual(value, {'ssh': ['usr/sbin/sshd']})

    def test_release_record_does_not_include_host_or_provisioning_paths(self):
        p = image.ROOT/'release'
        p.mkdir()
        compressed = p/'test.img.gz'
        compressed.write_bytes(b'compressed fixture')
        lock = image.ROOT/'lock.json'
        lock.write_text(json.dumps({'sources': {}, 'layer_sha256': 'fixture'}))
        info = {'profile': 'release', 'version': 'test', 'private': False,
                'source_build': False, 'output': '/owner/private/path',
                'work': '/owner/private/cache'}
        with mock.patch.object(image.subprocess, 'check_output', side_effect=['commit\n', '']):
            image.finish_record(self.args(lock=lock), info, compressed)
        record = (p/'build.json').read_text()
        self.assertNotIn('/owner/', record)
        self.assertTrue((p/'SHA256SUMS').is_file())

    def test_default_public_lock_uses_qualified_slim_profiles(self):
        value = json.loads((ROOT/'ports/rg353v/upstreams.lock.json').read_text())
        self.assertEqual(value['build']['kernel_profile'], 'rg353v-slim-v1')
        self.assertEqual(value['build']['userspace_profile'], 'rg353v-lean-v1')

    def test_private_rotation_preserves_old_paths_and_one_current_image(self):
        home = image.ROOT/'localdev'
        old, new = home/'images/old', home/'images/new'
        for p in (old, new):
            p.mkdir(parents=True)
            (p/'build.json').write_text('{"private": true}')
            (p/'image.img.gz').write_bytes(b'fixture')
        (home/'current').symlink_to('images/old', target_is_directory=True)
        image.promote_localdev(new)
        self.assertEqual((home/'current').resolve(), new.resolve())
        self.assertTrue(old.is_symlink())
        self.assertEqual((old/'image.img.gz').read_bytes(), b'fixture')
        self.assertTrue((image.ROOT/'resources/private-image-history/old').is_dir())

    def test_local_directories_are_ignored(self):
        for name in ('resources/not-public', 'localdev/not-public', 'release/not-public'):
            result = subprocess.run(['git', 'check-ignore', '-q', name], cwd=ROOT)
            self.assertEqual(result.returncode, 0, name)

    def test_documentation_relative_links_resolve(self):
        pages = [ROOT/'README.md', ROOT/'CREDITS.md', ROOT/'CONTRIBUTING.md', *sorted((ROOT/'wiki').glob('*.md'))]
        for page in pages:
            for link in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)', page.read_text()):
                if re.match(r'^[a-z]+:', link) or link.startswith('#'):
                    continue
                self.assertTrue((page.parent/link.split('#')[0]).exists(), f'{page.name}: {link}')


if __name__ == '__main__':
    unittest.main()
