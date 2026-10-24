#!/usr/bin/env python3
"""Safety and restoration tests. All block devices/commands are fakes."""
import importlib.machinery, importlib.util, os, sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
p=Path(__file__).resolve().parents[1]/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-storage-tools'
loader=importlib.machinery.SourceFileLoader('tools',str(p));spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
TOKEN='a'*64
T={'token':TOKEN,'label':'TF1 games','device':'/dev/mmcblk1p3','path':m.CONTENT,'kind':'exfat','options':'rw,nosuid,nodev','identity':('same',)}
ROW=(T['device'],m.CONTENT,'exfat','rw,nosuid,nodev')
class Tests(unittest.TestCase):
    def trial(self, *, busy=False, clean=True, swap=False, mounted_alias=False, fsck_error=False):
        calls=[];after=False
        def command(args):
            nonlocal after
            calls.append(args)
            if args[0]=='umount':
                if busy:raise m.Refused('busy')
                after=True
            return ''
        def mounts():return [ROW] if not after or busy else ([('/dev/mmcblk1p3','/other','exfat','rw')] if mounted_alias else [])
        with patch.object(m,'repair_power_ready',return_value=True),patch.object(m.os,'geteuid',return_value=0),patch.object(m.Path,'exists',return_value=False),patch.object(m,'discover',return_value=[T]),patch.object(m,'run',return_value=(0,'')),patch.object(m,'checked',side_effect=command),patch.object(m,'mounts',side_effect=mounts),patch.object(m,'identity',return_value=('changed',) if swap else T['identity']),patch.object(m,'exported',return_value=False),patch.object(m.os,'sync'),patch.object(m,'fsck',side_effect=m.Refused('timeout') if fsck_error else None,return_value=(clean,'')) as fsck:
            try:result=m.maintain(TOKEN,True)
            except Exception as e:result=str(e)
            return result,calls,fsck.call_count
    def test_busy_volume_is_not_checked_or_forced(self):
        result,calls,n=self.trial(busy=True);self.assertIn('busy',result);self.assertEqual(n,0)
        self.assertIn(['systemctl','start','slot-sharing.service'],calls)
        self.assertFalse(any('-f' in c or '-l' in c or c[0]=='mount' for c in calls))
    def test_repair_restores_original_mount_and_file_sharing(self):
        result,calls,n=self.trial();self.assertIn('verification passed',result);self.assertEqual(n,1)
        self.assertIn(['mount','-t','exfat','-o',T['options'],T['device'],m.CONTENT],calls)
        self.assertEqual(calls[-1],['systemctl','start','slot-sharing.service'])
    def test_uncorrected_errors_restore_read_only(self):
        result,calls,n=self.trial(clean=False);self.assertIn('read-only',result)
        cmd=next(c for c in calls if c[0]=='mount');self.assertIn('ro',cmd[4].split(','));self.assertNotIn('rw',cmd[4].split(','))
    def test_timeout_still_remounts_read_only(self):
        result,calls,n=self.trial(fsck_error=True);self.assertIn('timeout',result);self.assertTrue(any(c[0]=='mount' and 'ro' in c[4].split(',') for c in calls))
    def test_swapped_card_is_neither_checked_nor_mounted(self):
        result,calls,n=self.trial(swap=True);self.assertEqual(n,0);self.assertIn('changed',result);self.assertFalse(any(c[0]=='mount' for c in calls))
    def test_other_mount_prevents_fsck(self):
        result,calls,n=self.trial(mounted_alias=True);self.assertEqual(n,0);self.assertIn('still mounted',result)
    def test_invalid_token_and_missing_card(self):
        with patch.object(m,'repair_power_ready',return_value=True),patch.object(m.os,'geteuid',return_value=0):
            with self.assertRaises(m.Refused):m.maintain('bad',True)
        with patch.object(m,'repair_power_ready',return_value=True),patch.object(m.os,'geteuid',return_value=0),patch.object(m.Path,'exists',return_value=False),patch.object(m,'discover',return_value=[]):
            with self.assertRaisesRegex(m.Refused,'changed'):m.maintain(TOKEN,False)
    def test_targets_protect_system_double_mount_and_usb_export(self):
        ident=(T['device'],123,'c'*32,'1234','TF1')
        with patch.object(m,'identity',return_value=ident),patch.object(m,'exported',return_value=False),patch.object(m.Path,'is_dir',return_value=True):
            self.assertEqual(m.target(ROW,[ROW])['label'],'TF1 games (mmcblk1p3)')
            with self.assertRaises(m.Refused):m.target(ROW,[ROW,(T['device'],'/flash','vfat','rw')])
            with self.assertRaises(m.Refused):m.target(ROW,[ROW,(T['device'],'/other','exfat','ro')])
            with patch.object(m,'exported',return_value=True):
                with self.assertRaises(m.Refused):m.target(ROW,[ROW])
    def test_check_never_uses_repair_flag_and_repair_is_verified(self):
        with patch.object(m,'run',return_value=(0,'')) as run:
            self.assertTrue(m.fsck(T,False)[0]);run.assert_called_once_with(['fsck.exfat','-n',T['device']],timeout=60)
        with patch.object(m,'repair_power_ready',return_value=True),patch.object(m,'mounts',return_value=[]),patch.object(m,'identity',return_value=T['identity']),patch.object(m,'exported',return_value=False),patch.object(m,'run',side_effect=[(1,'corrected'),(0,'clean')]) as run:
            self.assertTrue(m.fsck(T,True)[0]);self.assertEqual(run.call_args_list[-1].args[0][1],'-n')
    def test_internal_emmc_rejected(self):
        with patch.object(m.Path,'resolve',return_value=Path('/dev/mmcblk0p3')),patch.object(m.Path,'stat',return_value=type('S',(),{'st_mode':0o60600})()),patch.object(m.Path,'read_text',return_value='MMC'):
            with self.assertRaisesRegex(m.Refused,'eMMC'):m.identity('/dev/mmcblk0p3')
    def test_commands_have_deadlines_and_bounded_output(self):
        self.assertEqual(m.run(['python3','-c','print("ok")'])[0],0)
        with self.assertRaises(m.Refused):m.run(['python3','-c','import time;time.sleep(10)'],timeout=.05)
        with self.assertRaises(m.Refused):m.run(['python3','-c','print("x"*1000000)'])
    def test_low_or_unknown_battery_refuses_before_unmount(self):
        with patch.object(m.os,'geteuid',return_value=0),patch.object(m.Path,'exists',return_value=False),patch.object(m,'discover',return_value=[T]),patch.object(m,'repair_power_ready',return_value=False),patch.object(m,'checked') as checked,patch.object(m,'run') as run:
            with self.assertRaisesRegex(m.Refused,'20%'):m.maintain(TOKEN,True)
            checked.assert_not_called();run.assert_not_called()
    def test_battery_status_checks_actual_charging_not_cable_presence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);b=root/'battery';b.mkdir()
            (b/'type').write_text('Battery');(b/'capacity').write_text('19');(b/'status').write_text('Discharging')
            self.assertFalse(m.repair_power_ready(root))
            (b/'status').write_text('Charging');self.assertTrue(m.repair_power_ready(root))
            (b/'status').write_text('Discharging');(b/'capacity').write_text('20');self.assertTrue(m.repair_power_ready(root))
            (b/'capacity').write_text('unknown');self.assertFalse(m.repair_power_ready(root))
    def test_multiple_passes_need_clean_verification_and_stop_at_three(self):
        for responses,expected,calls in [([(1,'fixed'),(1,'more'),(1,'fixed'),(0,'clean')],True,4), ([(1,'fixed'),(1,'still bad')]*3,False,6), ([(2,'fatal')],False,1)]:
            with patch.object(m,'repair_power_ready',return_value=True),patch.object(m,'mounts',return_value=[]),patch.object(m,'identity',return_value=T['identity']),patch.object(m,'exported',return_value=False),patch.object(m,'run',side_effect=responses) as run:
                self.assertEqual(m.fsck(T,True)[0],expected);self.assertEqual(run.call_count,calls)
    def test_power_loss_or_replaced_card_stops_additional_repair_writes(self):
        with patch.object(m,'repair_power_ready',side_effect=[True,False]),patch.object(m,'mounts',return_value=[]),patch.object(m,'identity',return_value=T['identity']),patch.object(m,'exported',return_value=False),patch.object(m,'run',side_effect=[(1,'fixed'),(1,'more')]) as run:
            with self.assertRaisesRegex(m.Refused,'20%'):m.fsck(T,True)
            self.assertEqual(run.call_count,2)
if __name__=='__main__':unittest.main()
