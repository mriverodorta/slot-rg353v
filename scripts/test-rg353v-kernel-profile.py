#!/usr/bin/env python3
"""Opt-in config isolation, hardware retention and dependency-result validation."""
import importlib.util
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT/'ports/rg353v/rocknix/slot-startup-profile'
spec = importlib.util.spec_from_file_location('kernel_profile', PKG/'tools/configure-kernel.py')
k = importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
policy = json.loads((PKG/'config/kernel-slim-v1.json').read_text())


class Profiles(unittest.TestCase):
    def baseline(self):
        values = dict(policy['require'])
        values.update({name: 'y' for group in policy['groups'].values() for name in group})
        values.update({name: 'y' for name in policy.get('defer_modules', [])})
        values['ROCKCHIP_DW_HDMI'] = 'y'
        values['CHARGER_GPIO'] = 'y'
        return '# Linux/arm64 7.0.2 Kernel Configuration\n' + ''.join(f'CONFIG_{a}={b}\n' for a,b in values.items())

    def test_strip_retains_board_and_unchanged_followups(self):
        result, changed = k.compose(self.baseline(), policy)
        k.validate(k.parse(result), policy)
        self.assertTrue(changed)
        self.assertEqual(k.parse(result)['ROCKCHIP_DW_HDMI'],
                         'n' if 'unused_hdmi' in policy['groups'] else 'y')
        self.assertEqual(k.parse(result)['CHARGER_GPIO'], 'y')
        self.assertEqual(k.parse(result)['USB_CONFIGFS_MASS_STORAGE'], 'y')
        self.assertEqual(k.parse(result)['RTW88_8821CS'], 'm')
        self.assertEqual(k.parse(result)['DRM_PANEL_SITRONIX_ST7703'], 'y')
        self.assertEqual(k.parse(result)['SQUASHFS_LZ4'], 'y')
        self.assertEqual(k.parse(result)['COMPAT'], 'y')
        self.assertEqual(k.parse(result)['BINFMT_MISC'], 'y')
        for symbol in ('BINFMT_ELF', 'BINFMT_SCRIPT', 'COREDUMP'):
            self.assertEqual(k.parse(result)[symbol], 'y')

    def test_bad_retention_fails_before_composition(self):
        for symbol in policy['require']:
            with self.subTest(symbol=symbol):
                broken=self.baseline().replace('CONFIG_'+symbol+'='+policy['require'][symbol], '# CONFIG_'+symbol+' is not set')
                with self.assertRaises(ValueError): k.compose(broken, policy)

    def test_resolved_dependency_loss_is_rejected(self):
        result,_ = k.compose(self.baseline(), policy)
        broken=result.replace('CONFIG_RTW88_8821CS=m', '# CONFIG_RTW88_8821CS is not set')
        with self.assertRaises(ValueError):k.validate(k.parse(broken), policy)
        broken=result+'CONFIG_BT=m\n'
        with self.assertRaises(ValueError):k.validate(k.parse(broken), policy)

    def test_unknown_profile_rejected(self):
        bad=dict(policy,id='other')
        with self.assertRaises(ValueError):k.compose(self.baseline(), bad)

    def test_deferred_hosts_keep_gadget_and_require_modules(self):
        baseline=self.baseline()
        for symbol in k.USB_HOST_MODULES:
            if 'CONFIG_'+symbol+'=' not in baseline:baseline+='CONFIG_'+symbol+'=y\n'
        selected=dict(policy,defer_modules=sorted(k.USB_HOST_MODULES))
        result,_=k.compose(baseline,selected)
        for symbol in k.USB_HOST_MODULES:self.assertEqual(k.parse(result)[symbol],'m')
        for symbol in ('USB_DWC3_DUAL_ROLE','USB_CONFIGFS_MASS_STORAGE'):
            self.assertEqual(k.parse(result)[symbol],'y')
        with self.assertRaises(ValueError):k.validate(k.parse(result.replace('CONFIG_USB_OHCI_HCD=m','CONFIG_USB_OHCI_HCD=y')),selected)
        with self.assertRaises(ValueError):k.compose(baseline,dict(policy,defer_modules=['USB_CONFIGFS']))

    def test_removal_cannot_overlap_hardware(self):
        bad=dict(policy,groups={'bad':['RTW88_8821CS']})
        with self.assertRaises(ValueError):k.compose(self.baseline(), bad)

    def test_smb_server_is_modular_and_dependency_resolution_is_checked(self):
        result, _ = k.compose(self.baseline(), policy)
        config = k.parse(result)
        self.assertEqual(config['SMB_SERVER'], 'm')
        self.assertEqual(config['NLS_UCS2_UTILS'], 'm')
        self.assertEqual(config['SMB_SERVER_SMBDIRECT'], 'n')
        for symbol, value in k.SMB_FEATURES.items():
            with self.subTest(symbol=symbol):
                changed = dict(config)
                changed[symbol] = 'y' if value != 'y' else 'n'
                with self.assertRaisesRegex(ValueError, 'Optional file-sharing'):
                    k.validate(changed, policy)
        for features in ({'SMB_SERVER': 'y'}, dict(k.SMB_FEATURES, UNKNOWN='m')):
            with self.assertRaises(ValueError):
                k.compose(self.baseline(), dict(policy, optional_features=features))

    def test_stage_then_baseline_restores_shared_builder_input(self):
        with tempfile.TemporaryDirectory() as name:
            tree=Path(name);base=tree/'projects/ROCKNIX/devices/RK3566/linux/linux.aarch64.conf'
            base.parent.mkdir(parents=True);base.write_text(self.baseline())
            k.stage(tree, PKG/'config/kernel-slim-v1.json', k.PROFILE)
            output=base.parent/'7.0.2/linux.aarch64.conf'
            self.assertEqual(k.parse(output.read_text())['BT'], 'n')
            k.stage(tree, PKG/'config/kernel-slim-v1.json')
            self.assertEqual(k.optional_file_sharing(base.read_text()),output.read_text())
            self.assertEqual(k.parse(output.read_text())['SMB_SERVER'], 'm')
            self.assertEqual(k.parse(output.read_text())['BT'], 'y')
            self.assertEqual(json.loads((tree/'.rg353v-kernel.json').read_text())['profile'],'baseline')

    def test_hdmi_removal_pairs_board_graph_and_baseline_clears_it(self):
        with tempfile.TemporaryDirectory() as name:
            tree=Path(name);base=tree/'projects/ROCKNIX/devices/RK3566/linux/linux.aarch64.conf'
            base.parent.mkdir(parents=True);base.write_text(self.baseline())
            selected=json.loads(json.dumps(policy))
            selected['groups']['unused_hdmi']=['ROCKCHIP_DW_HDMI']
            custom=tree/'kernel-slim-v1.json'
            custom.write_text(json.dumps(selected))
            shutil.copy2(PKG/'config/rg353v-internal-display.patch',tree/'rg353v-internal-display.patch')
            shutil.copy2(PKG/'config/rg353v-rtw88-regulatory.patch',tree/'rg353v-rtw88-regulatory.patch')
            k.stage(tree,custom,k.PROFILE)
            patch=tree/'projects/ROCKNIX/devices/RK3566/patches/linux/1013-slot-rg353v-internal-display.patch'
            self.assertIn('&hdmi_sound',patch.read_text())
            self.assertNotIn('rk3566-anbernic-rg353x.dtsi',patch.read_text())
            radio_patch=patch.with_name('1014-slot-rg353v-rtw88-regulatory.patch')
            self.assertIn('RTW_FLAG_RUNNING',radio_patch.read_text())
            self.assertEqual(k.parse((base.parent/'7.0.2/linux.aarch64.conf').read_text())['ROCKCHIP_DW_HDMI'],'n')
            k.stage(tree,custom)
            self.assertFalse(patch.exists())
            self.assertFalse(radio_patch.exists())
            ncm_patch=patch.with_name('1015-slot-rg353v-ncm-tx-timer.patch')
            self.assertEqual(ncm_patch.read_bytes(),(PKG/'config/rg353v-ncm-tx-timer.patch').read_bytes())
            self.assertIn('NETDEV_TX_BUSY',ncm_patch.read_text())


if __name__=='__main__':unittest.main()
