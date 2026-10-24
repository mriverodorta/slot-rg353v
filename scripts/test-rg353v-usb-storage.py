#!/usr/bin/env python3
"""USB content ownership, busy rollback, host eject and boot recovery tests."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'ports/rg353v/rocknix/slot-rg353v'
loader = importlib.machinery.SourceFileLoader('usb_storage', str(PORT/'scripts/slot-usb-storage'))
spec = importlib.util.spec_from_loader(loader.name, loader)
u = importlib.util.module_from_spec(spec)
loader.exec_module(u)

class UsbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for key in ('RUN','CACHE','GADGET','UDC','CONTENT','UNITDIR'):
            target = self.root / key.lower()
            target.mkdir()
            patcher = patch.object(u, key, target)
            patcher.start()
            self.addCleanup(patcher.stop)
        (u.CONTENT/'Config').mkdir()
        (u.CONTENT/'Config/slot.state').write_text('cart=\n')
        self.target = u.ContentTarget(Path('/dev/mmcblk0p3'), 'mmcblk0', 'MMC', 'a'*32, '1234-5678', 179)
        for name in ('content_target', 'content_identity'):
            patcher = patch.object(u, name, return_value=self.target);patcher.start();self.addCleanup(patcher.stop)
        patcher = patch.object(u, 'system_mounts_match');patcher.start();self.addCleanup(patcher.stop)
        patcher = patch.object(u, 'mounts', return_value=[]);patcher.start();self.addCleanup(patcher.stop)
        self.calls = []

    def command(self, args, **kwargs):
        self.calls.append(args)
        text = 'LoadState=loaded\nActiveState=active\nUnitFileState=static\n'
        if '--property=LoadState' in args: text = 'masked\n'
        if '--property=DropInPaths' in args: text = str(u.UNITDIR / (args[-1] + '.d') / '90-slot-usb-storage.conf') + '\n'
        return subprocess.CompletedProcess(args, 0, text, '')

    def test_eject_is_the_only_connected_host_exit(self):
        for state in ('configured', 'addressed', 'default', 'suspended', 'not attached'):
            self.assertIsNone(u.host_finished(True, '/dev/mmcblk0p3', state, True))
        self.assertEqual(u.host_finished(True, '', 'configured', False), 'ejected')

    def test_disconnect_requires_physical_cable_removal(self):
        self.assertIsNone(u.host_finished(True, '/dev/mmcblk0p3', 'not attached', False, True))
        self.assertEqual(u.host_finished(True, '/dev/mmcblk0p3', 'not attached', False, False), 'disconnected')
        self.assertIsNone(u.host_finished(True, '/dev/mmcblk0p3', 'default', False, False))

    def test_empty_waiting_media_cancels_including_approval_races(self):
        for state in ('not attached', 'default', 'addressed', 'configured', 'suspended'):
            self.assertIsNone(u.host_finished(False, '', state, False))
            self.assertEqual(u.host_finished(False, '', state, True), 'cancelled')

    def transfer_fixture(self, state='addressed'):
        session = u.Session(self.target)
        session.screen = Mock()
        session.screen.poll.return_value = None
        (u.UDC/'state').write_text(state)
        lun = u.GADGET/'functions/mass_storage.0/lun.0/file'
        lun.parent.mkdir(parents=True)
        lun.write_text('')
        read = Path.read_text
        def text(path, *args, **kwargs):
            if str(path) == '/sys/class/extcon/extcon0/state': return 'USB=1\nSDP=1\n'
            return read(path, *args, **kwargs)
        patcher = patch.object(Path, 'read_text', text)
        patcher.start()
        self.addCleanup(patcher.stop)
        return session, lun

    def test_pending_mac_approval_b_cancels_without_attaching_content(self):
        session, lun = self.transfer_fixture()
        def cancel(_):
            self.assertEqual(lun.read_text(), '')
            self.assertEqual((u.RUN/'phase').read_text(), 'waiting\n')
            (u.RUN/'cancel').touch()
        with patch.object(u.time, 'sleep', cancel), patch.object(u, 'write') as write:
            session.transfer()
        write.assert_not_called()
        self.assertFalse(session.media_shared)

    def test_cancel_wins_when_host_becomes_configured(self):
        session, _ = self.transfer_fixture('configured')
        (u.RUN/'cancel').touch()
        with patch.object(u, 'write') as write:
            session.transfer()
        write.assert_not_called()

    def test_media_attaches_only_after_configured_and_reset_cannot_cancel_it(self):
        session, lun = self.transfer_fixture()
        stages = []
        def step(_):
            stages.append((u.UDC/'state').read_text())
            if len(stages) == 1:
                self.assertEqual(lun.read_text(), '')
                (u.UDC/'state').write_text('configured')
            elif len(stages) == 2:
                self.assertEqual(lun.read_text().strip(), str(self.target.device))
                (u.UDC/'state').write_text('addressed')
                (u.RUN/'cancel').touch()
            else:
                self.assertIn('Eject SLOT on your computer first', (u.RUN/'status').read_text())
                self.assertEqual((u.RUN/'phase').read_text(), 'shared\n')
                lun.write_text('')  # Host ejects; it must never get reattached.
        with patch.object(u.time, 'sleep', step), patch.object(u, 'mounts', return_value=[]), patch.object(u, 'write', wraps=u.write) as write:
            session.transfer()
        self.assertEqual(write.call_args_list, [unittest.mock.call(lun, str(self.target.device))])
        self.assertTrue(session.media_shared)
        self.assertEqual(len(stages), 3)

    def test_mount_alias_found_before_media_insertion_aborts(self):
        session, lun = self.transfer_fixture('configured')
        with patch.object(u, 'mounts', return_value=[(str(self.target.device), '/alias', 'exfat')]), patch.object(u, 'write') as write:
            with self.assertRaisesRegex(u.StorageError, 'mounted USB'): session.transfer()
        write.assert_not_called()
        self.assertEqual(lun.read_text(), '')

    def test_cancel_arriving_during_mount_recheck_wins_before_media_insertion(self):
        session, _ = self.transfer_fixture('configured')
        def mounts():
            (u.RUN/'cancel').touch()
            return []
        with patch.object(u, 'mounts', mounts), patch.object(u, 'write') as write:
            session.transfer()
        write.assert_not_called()

    def test_setup_binds_an_empty_removable_drive(self):
        u.GADGET.rmdir()
        written = []
        read = Path.read_text
        mkdir = Path.mkdir
        def configfs_mkdir(path, *args, **kwargs):
            mkdir(path, *args, **kwargs)
            if path == u.GADGET:
                for name in ('strings', 'configs', 'functions'): mkdir(path/name, exist_ok=True)
            if path == u.GADGET/'configs/c.1': mkdir(path/'strings', exist_ok=True)
        def text(path, *args, **kwargs):
            if str(path) == '/storage/.cache/systemd-machine-id': return 'a'*32
            return read(path, *args, **kwargs)
        def write(path, value):
            written.append((path, value))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value+'\n')
            if path.name == 'removable': (path.parent/'file').write_text('')
        with patch.object(u, 'write', write), patch.object(Path, 'mkdir', configfs_mkdir), patch.object(Path, 'read_text', text), patch.object(u, 'mounts', return_value=[]):
            u.Session(self.target).setup()
        self.assertFalse(any(path.name == 'file' for path, _ in written))
        self.assertEqual(written[-1], (u.GADGET/'UDC', u.UDC.name))

    def test_busy_unmount_never_binds_and_restores_writer_masks(self):
        session = u.Session(self.target)
        def run(args, **kwargs):
            result = self.command(args, **kwargs)
            if args[0] == 'umount':
                raise u.StorageError('busy')
            return result
        # No gadget was created in this scenario.
        u.GADGET.rmdir()
        with patch.object(u, 'command', run), patch.object(u.os, 'sync'), patch.object(u, 'mounts', return_value=[(str(self.target.device), str(u.CONTENT), 'exfat')]):
            with self.assertRaisesRegex(u.StorageError, 'busy'):
                session.quiesce()
            self.assertFalse(session.unmounted)
            session.restore()
        self.assertFalse((u.CACHE/'owner.json').exists())
        self.assertFalse(session.masked)
        self.assertFalse(session.guards)
        self.assertTrue(all(call[1] != 'start' for call in self.calls))
        self.assertFalse(any('fsck.exfat' in call for call in self.calls))
        stopped = next(i for i,c in enumerate(self.calls) if c[:2] == ['systemctl','stop'])
        unmounted = next(i for i,c in enumerate(self.calls) if c[0] == 'umount')
        self.assertLess(stopped, unmounted)
        self.assertFalse(any('-l' in c or '-f' in c for c in self.calls))

    def test_detach_failure_never_remounts_or_unmasks(self):
        session = u.Session(self.target)
        session.unmounted = True
        session.masked = ['slot-rg353v.service']
        with patch.object(session, 'detach', side_effect=u.StorageError('still open')), patch.object(u, 'command', self.command):
            with self.assertRaises(u.StorageError): session.restore()
        self.assertEqual(self.calls, [])
        self.assertEqual(session.masked, ['slot-rg353v.service'])

    def test_controller_error_does_not_reclaim_shared_media(self):
        session = u.Session(self.target)
        session.media_shared = True
        session.unmounted = True
        with patch.object(session, 'detach') as detach, patch.object(u, 'command') as command:
            with self.assertRaisesRegex(u.StorageError, 'host has not released'): session.restore()
        detach.assert_not_called()
        command.assert_not_called()

    def test_remount_failure_retains_recovery_breadcrumb_and_masks(self):
        session = u.Session(self.target)
        session.unmounted = True
        session.masked = ['slot-rg353v.service']
        (u.CACHE/'owner.json').write_text('{}')
        (u.RUN/'active').touch()
        with patch.object(session, 'detach'), patch.object(u, 'status'), patch.object(u, 'command', side_effect=u.StorageError('check failed')):
            with self.assertRaises(u.StorageError): session.restore()
        self.assertTrue((u.CACHE/'owner.json').exists())
        self.assertTrue(session.unmounted)
        self.assertEqual(session.masked, ['slot-rg353v.service'])

    def test_usb_is_unbound_before_local_mount_and_frontend(self):
        session = u.Session(self.target)
        session.unmounted = True
        session.masked = ['slot-rg353v.service','storage-slotcontent.mount']
        def detach(): self.calls.append(['detach'])
        with patch.object(session, 'detach', detach), patch.object(u, 'status'), patch.object(u, 'command', self.command):
            session.restore()
        self.assertEqual(self.calls[0], ['detach'])
        mount = next(i for i,c in enumerate(self.calls) if c[0] == '/usr/bin/slot-mount-content')
        unmask = next(i for i,c in enumerate(self.calls) if c[-1] == 'slot-rg353v.service')
        self.assertLess(mount, unmask)

    def test_unmount_timeout_checks_actual_ownership_before_rollback(self):
        session = u.Session(self.target)
        def run(args, **kwargs):
            result = self.command(args, **kwargs)
            if args[0] == 'umount':
                raise subprocess.TimeoutExpired(args, 30)
            return result
        with patch.object(u, 'command', run), patch.object(u.os, 'sync'), patch.object(u, 'mounts', return_value=[]):
            with self.assertRaises(subprocess.TimeoutExpired): session.quiesce()
        self.assertTrue(session.unmounted)

    def test_a_second_local_mount_prevents_export(self):
        session = u.Session(self.target)
        with patch.object(u, 'command', self.command), patch.object(u.os, 'sync'), patch.object(u, 'mounts', return_value=[(str(self.target.device), '/another-mount', 'exfat')]):
            with self.assertRaisesRegex(u.StorageError, 'local mount'): session.quiesce()
        self.assertFalse(session.bound)

    def test_display_failure_waits_for_host_eject(self):
        session = u.Session(self.target)
        session.screen = Mock()
        session.screen.poll.return_value = 1
        session.media_shared = True
        (u.UDC/'state').write_text('configured')
        lun = u.GADGET/'functions/mass_storage.0/lun.0/file'
        lun.parent.mkdir(parents=True)
        lun.write_text(str(self.target.device))
        read = Path.read_text
        def text(path, *args, **kwargs):
            if str(path) == '/sys/class/extcon/extcon0/state': return 'USB=1\nSDP=1\n'
            return read(path, *args, **kwargs)
        def eject(_): lun.write_text('')
        with patch.object(Path, 'read_text', text), patch.object(u.time, 'sleep', eject), patch.object(u, 'status'), patch.object(u, 'event') as event:
            session.transfer()
        self.assertTrue(any('waiting for host eject' in call.args[0] for call in event.call_args_list))
        self.assertTrue(any('ejected' in call.args[0] for call in event.call_args_list))

    def test_start_failure_is_returned_to_the_menu(self):
        def run(args, **kwargs):
            if args[:2] == ['systemctl','start']:
                (u.RUN/'error').write_text('Eject the game with F first')
                return subprocess.CompletedProcess(args, 0, '', '')
            return subprocess.CompletedProcess(args, 0, 'failed\n', '')
        with patch.object(u, 'preflight'), patch.object(u, 'command', run), patch.object(u.sys, 'argv', ['slot-usb-storage','start']):
            with self.assertRaisesRegex(u.StorageError, 'Eject the game'): u.main()

    def test_fresh_install_needs_no_previous_os_update_to_take_locks(self):
        session=Mock();session.active=[]
        def path(name):
            name=str(name)
            return self.root/name.lstrip('/') if name.startswith('/storage/') else Path(name)
        with patch.object(u,'Path',side_effect=path), patch.object(u,'preflight',return_value=self.target), \
             patch.object(u,'Session',return_value=session), patch.object(u.signal,'signal'):
            u.run_session()
        self.assertTrue((self.root/'storage/slot-os-updates/control/lock').is_file())
        self.assertTrue((self.root/'storage/slot-manager/lock').is_file())
        session.transfer.assert_called_once()
        session.restore.assert_called_once()

    def test_start_waits_for_a_presented_screen_not_just_a_spawn(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[:2] == ['systemctl','show']:
                (u.RUN/'active').touch()
                (u.RUN/'screen-ready').touch()
                return subprocess.CompletedProcess(args, 0, 'active\n', '')
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(u, 'preflight'), patch.object(u, 'command', run), patch.object(u.time, 'sleep'), patch.object(u.sys, 'argv', ['slot-usb-storage','start']):
            u.main()
        self.assertTrue(any(c[:2] == ['systemctl','show'] for c in calls))

    def test_local_units_use_conditions_because_runtime_masks_do_not_override_them(self):
        session = u.Session(self.target)
        with patch.object(u, 'command', self.command), patch.object(u.os, 'sync'), patch.object(u, 'mounts', return_value=[]):
            session.quiesce()
        self.assertEqual(len(session.guards), 2)
        self.assertTrue(all(p.read_text() == u.GUARD for p in session.guards))
        self.assertFalse(any(c[:2] == ['systemctl','mask'] and c[-1].startswith('slot-bootstage') for c in self.calls))
        self.assertTrue(any(c == ['systemctl','daemon-reload'] for c in self.calls))

    def test_writers_remain_guarded_through_local_remount(self):
        session = u.Session(self.target)
        session.unmounted = True
        (u.RUN/'active').touch()
        def run(args, **kwargs):
            if args[0] == '/usr/bin/slot-mount-content':
                self.assertTrue((u.RUN/'active').exists())
                self.assertTrue((u.RUN/'restoring').exists())
            return self.command(args, **kwargs)
        with patch.object(session, 'detach'), patch.object(u, 'command', run), patch.object(u, 'status'):
            session.restore()
        self.assertFalse((u.RUN/'active').exists())
        self.assertFalse((u.RUN/'restoring').exists())

    def test_backing_uses_the_verified_session_target(self):
        s = (PORT/'scripts/slot-usb-storage').read_text()
        self.assertNotIn("DEVICE = Path('/dev/mmcblk0p3')", s)
        self.assertIn("write(lun, str(self.device))", s)
        self.assertNotIn('forced_eject', s)
        self.assertNotIn('mount -o', s)

    def test_boot_and_generic_helpers_guard_usb_ownership(self):
        s = (PORT/'scripts/slot-mount-content').read_text()
        self.assertLess(s.index('/run/slot-usb/active'), s.index('mountpoint -q'))
        self.assertIn('fsck.exfat -n "$content"', s)
        self.assertLess(s.index('fsck.exfat -n'), s.index('mount -t exfat'))
        self.assertIn('/run/slot-usb/active', (PORT/'scripts/slot-start').read_text())
        self.assertIn('/run/slot-usb/active', (PORT/'scripts/slot-sharing').read_text())
        self.assertIn('/run/slot-usb/active', (PORT/'scripts/slot-update').read_text())

    def test_installed_generic_usb_guard_is_idempotent(self):
        tool = PORT/'tools/configure-usb-storage.py'
        binary = self.root/'usr/bin/usbgadget'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/bash\necho original\n')
        unit = self.root/'usr/lib/systemd/system/storage-slotcontent.mount'
        unit.parent.mkdir(parents=True)
        unit.write_text('[Unit]\nDescription=Content\n[Mount]\nWhat=/dev/disk/by-label/SLOT\n')
        for _ in range(2): subprocess.run(['python3', str(tool), str(self.root)], check=True)
        self.assertEqual(binary.read_text().count('/run/slot-usb/active'), 1)
        self.assertEqual(unit.read_text().count('/run/slot-usb/active'), 1)

class TargetTests(unittest.TestCase):
    def table(self, disk='mmcblk1'):
        return [(f'/dev/{disk}p1', '/flash', 'vfat'),
                (f'/dev/{disk}p2', '/storage', 'ext4'),
                (f'/dev/{disk}p3', str(u.CONTENT), 'exfat')]

    def identity(self, device, cid='a'*32):
        disk=str(device).split('/')[-1][:-2]
        return u.ContentTarget(Path(device), disk, 'MMC' if disk=='mmcblk0' else 'SD', cid, '1234-5678', 179)

    def test_sd_and_emmc_choose_only_the_current_boot_disks_games_partition(self):
        for disk in ['mmcblk0', 'mmcblk1', 'mmcblk2']:
            with self.subTest(disk=disk), patch.object(u, 'content_identity', side_effect=self.identity) as probe:
                target=u.content_target(self.table(disk))
                self.assertEqual(target.device, Path(f'/dev/{disk}p3'))
                probe.assert_called_once_with(Path(f'/dev/{disk}p3'))

    def test_duplicate_slot_labels_do_not_select_a_different_disk(self):
        table=self.table()+[('/dev/mmcblk0p3','/unrelated','exfat')]
        with patch.object(u, 'content_identity', side_effect=self.identity) as probe:
            self.assertEqual(u.content_target(table).device, Path('/dev/mmcblk1p3'))
            probe.assert_called_once_with(Path('/dev/mmcblk1p3'))

    def test_mixed_boot_system_and_content_disks_are_refused_before_probing(self):
        for index in range(3):
            table=self.table();src,dst,kind=table[index];table[index]=(src.replace('mmcblk1','mmcblk0'),dst,kind)
            with patch.object(u, 'content_identity') as probe, self.assertRaisesRegex(u.StorageError, 'same disk'):
                u.content_target(table)
            probe.assert_not_called()

    def test_boot_and_system_partitions_cannot_be_exported_as_content(self):
        for suffix in ['p1','p2','', 'p4']:
            table=self.table();table[-1]=('/dev/mmcblk1'+suffix,str(u.CONTENT),'exfat')
            with patch.object(u,'content_identity') as probe, self.assertRaises(u.StorageError):u.content_target(table)
            probe.assert_not_called()

    def test_multiply_mounted_games_partition_is_refused(self):
        with patch.object(u,'content_identity') as probe, self.assertRaisesRegex(u.StorageError,'multiple local mounts'):
            u.content_target(self.table()+[('/dev/mmcblk1p3','/alias','exfat')])
        probe.assert_not_called()

    def test_replacement_card_cannot_be_bound_or_remounted(self):
        expected=self.identity('/dev/mmcblk1p3');changed=self.identity('/dev/mmcblk1p3','b'*32)
        session=u.Session(expected)
        with patch.object(u,'mounts',return_value=self.table()[:2]), patch.object(u,'content_identity',return_value=changed), patch.object(Path,'mkdir') as mkdir:
            with self.assertRaisesRegex(u.StorageError,'changed during USB handoff'):session.setup()
            mkdir.assert_not_called()

    def test_live_mount_reappearing_prevents_media_insertion(self):
        session=u.Session(self.identity('/dev/mmcblk1p3'))
        with patch.object(u,'mounts',return_value=self.table()), patch.object(u,'content_identity',return_value=session.target):
            with self.assertRaisesRegex(u.StorageError,'local mount'):session.verify_unmounted()

    def test_changed_boot_disk_prevents_remount_after_eject(self):
        session=u.Session(self.identity('/dev/mmcblk1p3'));session.unmounted=True
        with patch.object(session,'detach'), patch.object(u,'mounts',return_value=self.table('mmcblk0')[:2]), patch.object(u,'command') as command:
            with self.assertRaisesRegex(u.StorageError,'same disk'):session.restore()
            command.assert_not_called()
        self.assertTrue(session.unmounted)


if __name__ == '__main__': unittest.main()
