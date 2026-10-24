#!/usr/bin/env python3
"""Protect the board's firmware while pruning only explicitly foreign families."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'ports/rg353v/rocknix/slot-startup-profile'
spec=importlib.util.spec_from_file_location('firmware',PKG/'tools/configure-firmware.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Firmware(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'image';self.fw=self.root/'usr/lib/kernel-overlays/base/lib/firmware'
        self.meta=self.root/'usr/share/slot';(self.meta/'hardware').mkdir(parents=True)
        (self.meta/'os-profile.json').write_text(json.dumps({'device':'rg353v','userspace_profile':'rg353v-lean-v1'}))
        (self.meta/'hardware/profile.json').write_text(json.dumps({'model':'anbernic,rg353v','panel':'anbernic,rg353v-panel-v2'}))
        self.policy=json.loads((PKG/'config/firmware-rg353v.json').read_text())
        for name in self.policy['required_sha256']:
            self.write(name,b'board firmware')
            self.policy['required_sha256'][name]=hashlib.sha256(b'board firmware').hexdigest()
        self.write('brcm/other.bin',b'foreign Broadcom')
        self.write('rtw89/other.bin',b'foreign Realtek')
        self.write('rtw88/rtw8822c_fw.bin',b'other rtw88')
        self.write('rtl_bt/rtl8852bs_fw.bin',b'other bt')
        self.write('arm/mali/fw.bin',b'GPU firmware')
        self.write('rtw88/LICENSE.txt',b'license')
        self.path=self.root.parent/'policy.json'

    def write(self,name,data):
        p=self.fw/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)

    def prune(self):
        self.path.write_text(json.dumps(self.policy));return m.prune(self.root,self.path)

    def test_foreign_families_removed_required_radio_gpu_regdb_and_licenses_kept(self):
        result=self.prune()
        self.assertEqual(len(result['removed']),4)
        for name in self.policy['required_sha256']:self.assertTrue((self.fw/name).is_file())
        self.assertEqual((self.fw/'arm/mali/fw.bin').read_bytes(),b'GPU firmware')
        self.assertEqual((self.fw/'rtw88/LICENSE.txt').read_bytes(),b'license')
        output=self.meta/'hardware/firmware-trim.json';first=output.read_bytes()
        self.prune();self.assertEqual(output.read_bytes(),first)

    def test_baseline_untouched(self):
        (self.meta/'os-profile.json').write_text('{}')
        self.assertEqual(self.prune()['removed'],[])
        self.assertTrue((self.fw/'brcm/other.bin').exists())

    def test_changed_board_or_firmware_rejected_before_any_deletion(self):
        (self.fw/'rtw88/rtw8821c_fw.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed required'):self.prune()
        self.assertTrue((self.fw/'brcm/other.bin').exists())
        (self.meta/'hardware/profile.json').write_text('{"model":"other"}')
        with self.assertRaisesRegex(ValueError,'hardware profile'):self.prune()
        self.assertTrue((self.fw/'brcm/other.bin').exists())

    def test_symlink_cannot_escape_trim_or_required_paths(self):
        foreign=self.fw/'rtw89/other.bin';foreign.unlink();foreign.symlink_to('/dev/null')
        with self.assertRaisesRegex(ValueError,'symlink'):self.prune()
        self.assertTrue((self.fw/'brcm/other.bin').exists())
        foreign.unlink();board=self.fw/'rtw88/rtw8821c_fw.bin';board.unlink();board.symlink_to('/dev/null')
        with self.assertRaisesRegex(ValueError,'symlink'):self.prune()

    def test_policy_cannot_delete_protected_firmware(self):
        self.policy['remove_files'].append('rtw88/rtw8821c_fw.bin')
        with self.assertRaisesRegex(ValueError,'required file'):self.prune()
        self.assertTrue((self.fw/'brcm/other.bin').exists())

    def test_invalid_policy_paths_are_rejected(self):
        self.policy['remove_families'].append('../outside')
        with self.assertRaisesRegex(ValueError,'Invalid firmware'):self.prune()
        self.assertTrue((self.fw/'brcm/other.bin').exists())


if __name__=='__main__':unittest.main()
