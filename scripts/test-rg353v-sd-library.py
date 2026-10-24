#!/usr/bin/env python3
import contextlib, importlib.machinery, importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

p=Path(__file__).resolve().parents[1]/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-sd-library'
loader=importlib.machinery.SourceFileLoader('sd_library',str(p));spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)

class Libraries(unittest.TestCase):
    def test_slots_use_controller_identity_not_block_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp)
            for controller,slot in m.CONTROLLERS.items():
                d=r/controller/'mmcblk9';(d/'device').mkdir(parents=True);(d/'device/type').write_text('SD')
                self.assertEqual(m.slot_for(d),slot)
                (d/'device/type').write_text('MMC');self.assertIsNone(m.slot_for(d))
            self.assertIsNone(m.slot_for(r/'mmcblk0p3'))

    def simulate(self,cards,has_games=True,existing=None):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);r=Path(self.tmp.name);base=r/'run';base.mkdir();table=existing or {};calls=[]
        nodes={}
        for slot in cards:
            d=r/cards[slot];(d/'device').mkdir(parents=True);(d/'device/serial').write_text('serial-'+slot);nodes[slot]=d
        def run(*args):
            calls.append(tuple(map(str,args)))
            if args[0]=='mount':
                dev,target=str(args[-2]),Path(args[-1]);table[str(target)]=[dev,str(target),'exfat',str(args[4]),'0','0']
                if has_games:(target/'Games').mkdir(exist_ok=True)
            elif args[0]=='umount':table.pop(str(args[1]),None)
            return ''
        with patch.object(m,'BASE',base),patch.object(m,'devices',return_value=nodes),patch.object(m,'candidates',side_effect=lambda n:[Path('/dev')/(n.name+'p3')]),patch.object(m,'mounted',side_effect=lambda:dict(table)),patch.object(m,'run',side_effect=run):
            first=m.refresh();second=m.refresh()
        return base,calls,first,second

    def test_both_cards_mount_readonly_and_repeat_does_not_remount(self):
        base,calls,first,second=self.simulate({'TF1':'mmcblk4','TF2':'mmcblk7'})
        mounts=[c for c in calls if c[0]=='mount'];self.assertEqual(len(mounts),2)
        self.assertTrue(all('ro,nosuid,nodev,noexec,noatime' in c for c in mounts))
        self.assertEqual((base/'roots').read_text().splitlines(),[str(base/'TF1'),str(base/'TF2')])
        self.assertEqual([x['state'] for x in second],['Ready','Ready'])

    def test_game_save_location_mounts_cards_writable_without_extra_remounts(self):
        with patch.object(m,'save_location',return_value='game'):
            base,calls,first,second=self.simulate({'TF1':'mmcblk4'})
        self.assertEqual(len([c for c in calls if c[0]=='mount']),1)
        self.assertFalse(first[0]['readonly']);self.assertEqual(second[0]['state'],'Ready')
        self.assertIn('rw,nosuid,nodev,noexec,noatime',next(c for c in calls if c[0]=='mount'))

    def test_empty_card_not_used_or_modified(self):
        base,calls,first,second=self.simulate({'TF1':'mmcblk4'},False)
        self.assertEqual((base/'roots').read_text().strip(),'')
        self.assertTrue(any(c[0]=='umount' for c in calls))
        self.assertFalse((base/'TF1/Games').exists())

    def test_no_cards_is_valid_and_never_mounts_internal(self):
        base,calls,first,second=self.simulate({})
        self.assertFalse(calls);self.assertEqual([x['state'] for x in first],['No card','No card'])

class Ejection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.base=self.root/'run';self.base.mkdir()
        self.node=self.root/'mmcblk9';(self.node/'device').mkdir(parents=True)
        (self.node/'device/cid').write_text('a'*32)
        (self.node/'device/serial').write_text('serial')
        self.target=str(self.base/'TF2');Path(self.target).mkdir()
        (Path(self.target)/'Games').mkdir()
        self.table={self.target:['/dev/mmcblk9p3',self.target,'exfat','ro,noatime']}
        self.calls=[]
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.object(m,'BASE',self.base))
        stack.enter_context(patch.object(m,'devices',return_value={'TF2':self.node}))
        stack.enter_context(patch.object(m,'mounted',side_effect=lambda:dict(self.table)))
        stack.enter_context(patch.object(m,'mount_rows',side_effect=lambda:list(self.table.values())))
        stack.enter_context(patch.object(m,'run',side_effect=self.run_command))
        stack.enter_context(patch.object(m.os,'geteuid',return_value=0))
    def run_command(self,*args):
        self.calls.append(tuple(map(str,args)))
        if args[0]=='umount': self.table.pop(str(args[1]),None)
        return ''
    def token(self):return m.card_id(self.node)
    def test_eject_unmounts_normally_publishes_no_games_and_stays_ejected(self):
        token=self.token()
        self.assertIn('safe to remove',m.change_card('eject','TF2',token))
        self.assertEqual(self.calls,[('umount',self.target)])
        self.assertEqual(m.card_rows()[1]['action'],'mount')
        with patch.object(m,'candidates',side_effect=AssertionError('must not remount')):
            for _ in range(3): self.assertEqual(m.refresh()[1]['state'],'Safe to remove')
        self.assertEqual((self.base/'roots').read_text().strip(),'')
    def test_mount_is_explicit_and_old_identity_is_refused(self):
        token=self.token();m.change_card('eject','TF2',token)
        with self.assertRaisesRegex(RuntimeError,'changed'):m.change_card('mount','TF2','b'*64)
        m.change_card('mount','TF2',token)
        self.assertFalse((self.base/'TF2.ejected').exists())
    def test_reinsertion_of_same_card_clears_ejected_marker(self):
        token=self.token();m.change_card('eject','TF2',token)
        # Same CID in a new sysfs object after remove/insert.
        with patch.object(m,'card_id',return_value='c'*64):
            self.assertFalse(m.suppressed('TF2',self.node))
        self.assertFalse((self.base/'TF2.ejected').exists())
    def test_same_card_reinserted_with_reused_inode_has_new_disk_sequence(self):
        (self.node/'diskseq').write_text('100\n')
        token=self.token();m.change_card('eject','TF2',token)
        self.assertTrue(m.suppressed('TF2',self.node))
        # Linux assigns a fresh sequence on reinsert, even if paths/inodes match.
        (self.node/'diskseq').write_text('101\n')
        self.assertNotEqual(self.token(),token)
        self.assertFalse(m.suppressed('TF2',self.node))
        with self.assertRaisesRegex(RuntimeError,'changed'):
            m.change_card('mount','TF2',token)
    def test_hotplug_refresh_refuses_active_game_or_usb_export_before_mounting(self):
        for guard in [RuntimeError('Eject the game with F first'),RuntimeError('Exit USB storage first')]:
            with self.subTest(guard=str(guard)),patch.object(m,'idle_required',side_effect=guard):
                with self.assertRaises(RuntimeError):m.refresh(require_idle=True)
        self.assertEqual(self.calls,[])
    def test_hotplug_reinsertion_remounts_same_card_and_republishes_roots(self):
        (self.node/'diskseq').write_text('100\n')
        m.change_card('eject','TF2',self.token())
        self.assertEqual(m.refresh()[1]['state'],'Safe to remove')
        (self.node/'diskseq').write_text('101\n')
        original=self.run_command
        def mount(*args):
            if args[0]=='mount':
                self.table[self.target]=['/dev/mmcblk9p3',self.target,'exfat','ro,noatime']
            return original(*args)
        with patch.object(m,'candidates',return_value=[Path('/dev/mmcblk9p3')]),patch.object(m,'run',side_effect=mount):
            self.assertEqual(m.refresh(require_idle=True)[1]['state'],'Ready')
            self.assertEqual(m.refresh(require_idle=True)[1]['state'],'Ready')
        self.assertEqual((self.base/'roots').read_text().splitlines(),[self.target])
        self.assertEqual(len([c for c in self.calls if c[0]=='mount']),1)
    def test_busy_unmount_never_marks_safe(self):
        with patch.object(m,'run',side_effect=RuntimeError('target is busy')):
            with self.assertRaisesRegex(RuntimeError,'busy'):m.change_card('eject','TF2',self.token())
        self.assertFalse((self.base/'TF2.ejected').exists())
        self.assertEqual(m.card_rows()[1]['state'],'Mounted')
    def test_system_and_primary_content_disks_are_protected(self):
        for where in ['/','/flash','/storage','/storage/slotcontent']:
            with self.subTest(where=where):
                self.table[where]=['/dev/mmcblk9p1',where,'ext4','rw']
                self.assertEqual(m.card_rows()[1]['action'],'')
                with self.assertRaisesRegex(RuntimeError,'protected'):m.change_card('eject','TF2',self.token())
                del self.table[where]
        self.assertEqual(self.calls,[])
    def test_other_mounts_and_holders_refuse_eject(self):
        self.table['/other']=['/dev/mmcblk9p1','/other','vfat','rw']
        with self.assertRaisesRegex(RuntimeError,'elsewhere'):m.change_card('eject','TF2',self.token())
        del self.table['/other']
        (self.node/'holders/dm-0').mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError,'another device'):m.change_card('eject','TF2',self.token())
        self.assertEqual(self.calls,[])
    def test_disappearing_card_or_changed_cid_never_uses_old_selection(self):
        token=self.token();(self.node/'device/cid').write_text('b'*32)
        with self.assertRaisesRegex(RuntimeError,'changed'):m.change_card('eject','TF2',token)
        self.assertEqual(self.calls,[])
    def test_unmount_returning_success_but_still_mounted_is_not_safe(self):
        with patch.object(m,'run',return_value=''):
            with self.assertRaisesRegex(RuntimeError,'still mounted'):m.change_card('eject','TF2',self.token())
        self.assertFalse((self.base/'TF2.ejected').exists())
    def test_running_game_and_usb_storage_block_eject(self):
        state=self.root/'slot.state';state.write_text('cart=Zelda\\n')
        with patch.object(m,'GAME_STATE',state):
            with self.assertRaisesRegex(RuntimeError,'game with F'):m.change_card('eject','TF2',self.token())
        active=self.root/'usb-active';active.touch()
        with patch.object(m,'USB_ACTIVE',active):
            with self.assertRaisesRegex(RuntimeError,'USB storage'):m.change_card('eject','TF2',self.token())
        self.assertEqual(self.calls,[])
    def test_hidden_overmounts_are_not_treated_as_unmounted(self):
        self.table.clear()
        hidden=['/dev/mmcblk9p3','/other','exfat','ro']
        with patch.object(m,'mount_rows',return_value=[hidden]):
            with self.assertRaisesRegex(RuntimeError,'elsewhere'):m.change_card('eject','TF2',self.token())
        self.assertFalse((self.base/'TF2.ejected').exists())
    def test_manually_remounted_card_is_never_reported_safe(self):
        token=self.token();m.change_card('eject','TF2',token)
        self.table['/other']=['/dev/mmcblk9p3','/other','exfat','ro']
        self.assertEqual(m.card_rows()[1]['state'],'Mounted')
        self.assertEqual(m.refresh()[1]['state'],'In use elsewhere')
    def test_disk_parser_handles_multidigit_mmc_numbers(self):
        self.assertEqual(m.disk_name('/dev/mmcblk12p3'),'mmcblk12')
        self.assertEqual(m.disk_name('/dev/mmcblk12'),'mmcblk12')

class SaveLocation(unittest.TestCase):
    run_command = Ejection.run_command
    token = Ejection.token
    def setUp(self):
        Ejection.setUp(self)
        self.pref=self.root/'Config/save-location'
        self.pref.parent.mkdir()
        self.state=self.root/'slot.state';self.state.write_text('cart=\n')
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.object(m,'SAVE_LOCATION',self.pref))
        stack.enter_context(patch.object(m,'GAME_STATE',self.state))
        original=self.run_command
        def remount(*args):
            if args[0]=='mount':
                target=str(args[-1]);self.table[target][3]=str(args[2]).removeprefix('remount,')
            return original(*args)
        stack.enter_context(patch.object(m,'run',side_effect=remount))
        self.table[self.target][3]='ro,nosuid,nodev,noexec,noatime'
    def test_defaults_system_and_switches_both_ways_without_touching_progress(self):
        self.assertEqual(m.save_location(),'system')
        (Path(self.target)/'Saves').mkdir();save=Path(self.target)/'Saves/test.sav';save.write_bytes(b'keep')
        m.change_save_location('game');self.assertEqual(self.pref.read_text(),'game\n')
        self.assertIn('rw',self.table[self.target][3].split(','))
        m.change_save_location('system');self.assertEqual(m.save_location(),'system')
        self.assertIn('ro',self.table[self.target][3].split(','));self.assertEqual(save.read_bytes(),b'keep')
        self.assertEqual(self.state.read_text(),'cart=\n')
    def test_active_game_blocks_location_change_and_mount(self):
        self.state.write_text('cart=Zelda\n')
        with self.assertRaisesRegex(RuntimeError,'Eject'):m.change_save_location('game')
        self.assertFalse(self.pref.exists());self.assertFalse(self.calls)
    def test_failure_rolls_back_mount_and_keeps_old_preference(self):
        tf1=str(self.base/'TF1');Path(tf1).mkdir()
        self.table[tf1]=self.table.pop(self.target);self.table[tf1][1]=tf1
        self.table[self.target]=['/dev/mmcblk8p1',self.target,'exfat','ro,nosuid,nodev,noexec']
        with patch.object(m,'devices',return_value={'TF1':self.node}):
            with self.assertRaisesRegex(RuntimeError,'Card changed'):m.change_save_location('game')
        self.assertEqual(m.save_location(),'system')
        self.assertIn('ro',self.table[tf1][3].split(','))
        self.assertEqual([c[2].split(',')[1] for c in self.calls if c[0]=='mount'],['rw','ro'])
    def test_game_mode_card_can_still_be_safely_ejected(self):
        m.change_save_location('game')
        self.assertIn('safe to remove',m.change_card('eject','TF2',self.token()))
        self.assertFalse(self.table)

if __name__=='__main__':unittest.main()
