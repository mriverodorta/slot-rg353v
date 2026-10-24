#!/usr/bin/env python3
"""Offline boot policy, explicit grants and developer-mode restoration."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('services',str(ROOT/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-services'))
spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)

class Services(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.calls=[];self.active=set();self.fail=None
        self.c=m.Controller(self.root/'storage',self.root/'run',self.run_command,sysroot=self.root/'sys')
        self.credentials=self.c.storage/'.cache/NetworkManager/profile';self.credentials.parent.mkdir(parents=True);self.credentials.write_bytes(b'private fixture credentials')
    def run_command(self,args):
        self.calls.append(args);rc=0
        if args[:2]==['systemctl','is-active']:rc=0 if args[-1] in self.active else 3
        elif args[:2]==['systemctl','start']:
            if self.fail and self.fail in args:self.fail=None;return subprocess.CompletedProcess(args,1,'','')
            self.active.update(n for n in args[2:] if n.endswith('.service'))
        elif args[:2]==['systemctl','stop']:self.active.difference_update(args[2:])
        return subprocess.CompletedProcess(args,rc,'','')
    def test_status_starts_nothing_and_ignores_old_network_preferences(self):
        cfg=self.c.storage/'.config/system/configs/system.cfg';cfg.parent.mkdir(parents=True);cfg.write_text('wifi.enabled=1\nssh.enabled=1\nsamba.enabled=1\n')
        self.assertEqual(self.c.status(),{'protocol':'1','wifi':'0','developer':'0','time':'0'})
        self.assertEqual(self.calls,[]);self.assertFalse(self.c.policy.exists())
    def test_wifi_alone_does_not_enable_remote_services_or_ntp(self):
        self.c.wifi(True)
        self.assertTrue(self.c.allowed('wifi'))
        for feature in ['sharing','ssh','time']:self.assertFalse(self.c.allowed(feature))
        self.assertTrue({'sshd.service','slot-sharing.service','systemd-timesyncd.service'}.isdisjoint(self.active))
        self.assertEqual(self.credentials.read_bytes(),b'private fixture credentials')
    def test_developer_mode_restores_all_extras_but_a_new_session_has_no_grants(self):
        self.c.set_developer(True)
        self.assertTrue(self.c.developer())
        self.assertTrue(all(self.c.allowed(f) for f in m.FEATURES))
        self.assertTrue({'sshd.service','slot-sharing.service','systemd-timesyncd.service','NetworkManager.service'}<=self.active)
        fresh=m.Controller(self.c.storage,self.root/'newrun',self.run_command)
        self.assertTrue(fresh.developer());self.assertFalse(any(fresh.allowed(f) for f in m.FEATURES))
        fresh.set_developer(True);self.assertTrue(all(fresh.allowed(f) for f in m.FEATURES))
    def test_developer_off_stops_everything_and_preserves_credentials(self):
        self.c.set_developer(True);self.c.set_developer(False)
        self.assertFalse(self.c.developer());self.assertFalse(any(self.c.allowed(f) for f in m.FEATURES))
        self.assertTrue(set(m.STOP).isdisjoint(self.active))
        self.assertEqual(self.credentials.read_bytes(),b'private fixture credentials')
    def test_enabling_extras_without_wifi_is_rejected_without_starting_services(self):
        for feature in ['ssh','sharing']:
            with self.assertRaises(m.ServiceError):self.c.prepare(feature)
        with self.assertRaises(m.ServiceError):self.c.time(True)
        self.assertEqual(self.calls,[])
    def test_failed_developer_activation_returns_to_offline_policy(self):
        self.fail='NetworkManager.service'
        with self.assertRaises(m.ServiceError):self.c.set_developer(True)
        self.assertFalse(self.c.developer());self.assertFalse(any(self.c.allowed(f) for f in m.FEATURES))
        self.assertTrue(set(m.STOP).isdisjoint(self.active))
    def test_wifi_off_also_stops_session_extras_without_erasing_developer_policy(self):
        self.c.set_developer(True);self.c.wifi(False)
        self.assertTrue(self.c.developer());self.assertTrue(self.c.allowed('ssh'))
        self.assertFalse(any(self.c.allowed(f) for f in ('wifi','sharing','time')))
        self.assertTrue(set(m.STOP).isdisjoint(self.active))

    def test_wifi_cycle_restores_explicit_ssh_choice_without_enabling_other_extras(self):
        self.c.wifi(True);self.c.prepare('ssh');self.c.flag('ssh',True)
        self.active.add('sshd.service')
        self.c.wifi(False)
        self.assertTrue(self.c.allowed('ssh'));self.assertNotIn('sshd.service',self.active)
        self.c.wifi(False)  # Repeated Off requests must retain the choice.
        self.c.wifi(True)
        self.assertIn('sshd.service',self.active)
        self.assertFalse(self.c.allowed('sharing'));self.assertFalse(self.c.allowed('time'))

    def test_turning_ssh_off_while_wifi_is_off_cancels_automatic_restoration(self):
        self.c.set_developer(True);self.c.wifi(False)
        self.c.flag('ssh',False)  # Same session flag removed by slot-ssh Off.
        self.c.wifi(True)
        self.assertNotIn('sshd.service',self.active)

    def test_ssh_restart_failure_preserves_wifi_and_can_be_retried(self):
        self.c.set_developer(True);self.c.wifi(False);self.fail='sshd.service'
        with self.assertRaises(m.ServiceError):self.c.wifi(True)
        self.assertTrue(self.c.allowed('wifi'));self.assertTrue(self.c.allowed('ssh'))
        self.assertIn('NetworkManager.service',self.active)
        self.c.wifi(True);self.assertIn('sshd.service',self.active)

    def test_developer_off_cancels_ssh_restoration_in_same_boot(self):
        self.c.set_developer(True);self.c.wifi(False);self.c.set_developer(False)
        self.c.wifi(True)
        self.assertFalse(self.c.allowed('ssh'));self.assertNotIn('sshd.service',self.active)

    def test_ssh_choice_does_not_survive_a_new_boot(self):
        self.c.set_developer(True);self.c.wifi(False)
        fresh=m.Controller(self.c.storage,self.root/'newrun',self.run_command)
        fresh.wifi(True)
        self.assertFalse(fresh.allowed('ssh'));self.assertNotIn('sshd.service',self.active)

    def test_failed_wifi_reconnect_retains_ssh_intent_without_running_it(self):
        self.c.set_developer(True);self.c.wifi(False);self.fail='NetworkManager.service'
        with self.assertRaises(m.ServiceError):self.c.wifi(True)
        self.assertTrue(self.c.allowed('ssh'));self.assertFalse(self.c.allowed('wifi'))
        self.assertNotIn('sshd.service',self.active)
        self.c.wifi(True);self.assertIn('sshd.service',self.active)

    def test_removed_ssh_module_cannot_restart_from_a_retained_choice(self):
        self.c.set_developer(True);self.c.wifi(False)
        p=self.c.storage/'.config/slot/features-v1';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('slot-features-v1\nwifi\n')
        self.c.wifi(True)
        self.assertNotIn('sshd.service',self.active)
    def test_existing_developer_policy_preserves_working_access_if_sharing_fails(self):
        self.c.set_developer(True)
        self.fail='slot-sharing.service'
        with self.assertRaises(m.ServiceError):self.c.set_developer(True)
        self.assertTrue(self.c.developer())
        self.assertTrue({'sshd.service','NetworkManager.service'}<=self.active)

    def test_sharing_runtime_configuration_is_prepared_only_on_request(self):
        self.c.wifi(True)
        self.assertNotIn(['/usr/bin/slot-ksmbd','prepare'],self.calls)
        self.c.prepare('sharing')
        self.assertIn(['/usr/bin/slot-ksmbd','prepare'],self.calls)
        self.assertFalse((self.c.runtime/'samba').exists())
        self.c.prepare('sharing')
        self.assertEqual(self.calls.count(['/usr/bin/slot-ksmbd','prepare']),2)
        self.assertNotIn(['/usr/lib/autostart/common/007-rootpw'], self.calls)
        self.assertFalse((self.c.flags/'auth.ready').exists())

    def test_recovery_cancellation_finishes_before_its_backend_is_stopped(self):
        self.c.wifi(True);self.calls.clear();self.c.wifi(False)
        stops=[a for a in self.calls if a[:2]==['systemctl','stop']]
        self.assertEqual(stops[0],['systemctl','stop','slot-wifi-probe-recovery.service'])
        self.assertIn('NetworkManager.service',stops[1])
        unit=(ROOT/'ports/rg353v/rocknix/slot-rg353v/system.d/slot-wifi-probe-recovery.service').read_text()
        self.assertIn('SuccessExitStatus=SIGTERM',unit)
        self.assertIn('TimeoutStartSec=75',unit)

    def test_uninstalled_services_cannot_be_enabled_and_developer_skips_them(self):
        p=self.c.storage/'.config/slot/features-v1';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('slot-features-v1\nwifi\ndeveloper\n')
        self.c.set_developer(True)
        self.assertTrue(self.c.allowed('wifi'))
        for feature in ('ssh','sharing','time'):
            self.assertFalse(self.c.allowed(feature))
        self.assertNotIn('sshd.service',self.active)
        with self.assertRaises(m.ServiceError):self.c.prepare('ssh')
        with self.assertRaises(m.ServiceError):self.c.time(True)

    def test_module_absence_skips_missing_units_and_wifi_tools(self):
        p=self.c.storage/'.config/slot/features-v1';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('slot-features-v1\n')
        self.c.wifi(False);self.c.time(False)
        self.assertEqual(self.calls,[])
        p.write_text('slot-features-v1\nwifi\nssh\n')
        self.c.wifi(False)
        args=[v for call in self.calls for v in call]
        self.assertIn('sshd.service',args)
        for name in ('systemd-timesyncd.service','slot-sharing.service','wsdd2.service'):
            self.assertNotIn(name,args)

    def test_private_setup_developer_policy_does_not_start_unselected_services(self):
        p=self.c.storage/'.config/slot/setup-developer-features-v1';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('slot-features-v1\nwifi\nssh\ndeveloper\n')
        self.c.set_developer(True)
        self.assertTrue(self.c.allowed('ssh'));self.assertFalse(self.c.allowed('sharing'))
        self.assertFalse(self.c.allowed('time'))
        self.assertTrue(self.c.installed('sharing'),'runtime startup policy is not installed inventory')

    def usb_ready(self):
        gadget=self.c.sysroot/'kernel/config/usb_gadget/slot-network'
        gadget.mkdir(parents=True);(gadget/'UDC').write_text('fcc00000.usb\n')
        (self.c.sysroot/'class/net/slotusb0').mkdir(parents=True)
        self.c.usb(True)

    def test_usb_grant_requires_the_owned_bound_gadget_and_interface(self):
        with self.assertRaises(m.ServiceError):self.c.usb(True)
        self.assertFalse(self.c.allowed('usb'));self.assertEqual(self.calls,[])
        self.usb_ready();self.assertTrue(self.c.allowed('usb'));self.assertTrue(self.c.allowed('network'))
        self.assertFalse(self.c.allowed('wifi'));self.assertEqual(self.calls,[])

    def test_usb_can_prepare_ssh_and_sharing_without_wifi_nm_ntp_or_https(self):
        self.usb_ready();self.c.prepare('ssh');self.c.prepare('sharing')
        self.assertTrue((self.c.flags/'auth.ready').exists())
        self.assertEqual(sum(a==['/usr/lib/autostart/common/007-rootpw'] for a in self.calls),1)
        text=repr(self.calls)
        for name in ['NetworkManager','openssl-config','network-base','rtw88','timesyncd']:
            self.assertNotIn(name,text)
        self.assertFalse(self.c.allowed('wifi'));self.assertFalse(self.c.allowed('time'))

    def test_wifi_off_keeps_explicit_usb_ssh_and_sharing_and_stops_internet_services(self):
        self.c.set_developer(True);self.usb_ready();self.c.wifi(False)
        self.assertTrue(self.c.allowed('usb'));self.assertFalse(self.c.allowed('wifi'))
        self.assertTrue(self.c.allowed('ssh'));self.assertTrue(self.c.allowed('sharing'))
        self.assertTrue({'sshd.service','slot-sharing.service'}<=self.active)
        self.assertTrue({'NetworkManager.service','slot-wpa-supplicant.service','systemd-resolved.service','systemd-timesyncd.service'}.isdisjoint(self.active))
        self.c.usb(False)
        self.assertFalse(self.c.allowed('usb'));self.assertTrue(self.c.allowed('ssh'))
        self.assertFalse(any(self.c.allowed(f) for f in ('wifi','sharing','time')))
        self.assertTrue(set(m.STOP).isdisjoint(self.active))

    def test_usb_transport_return_restores_only_previously_selected_ssh(self):
        self.usb_ready();self.c.flag('ssh',True);self.active.add('sshd.service')
        self.c.usb(False);self.assertNotIn('sshd.service',self.active)
        self.c.usb(True);self.assertIn('sshd.service',self.active)
        self.assertFalse(self.c.allowed('sharing'));self.assertFalse(self.c.allowed('time'))

    def test_explicit_network_time_accepts_a_usb_internet_lease_without_wifi(self):
        self.usb_ready()
        state=self.c.runtime/'slot-usb-network/state.json';state.parent.mkdir(parents=True)
        state.write_text('{"internet":true,"lease":"192.168.137.2/24"}')
        self.c.time(True)
        self.assertTrue(self.c.allowed('time'));self.assertFalse(self.c.allowed('wifi'))
        self.assertIn('systemd-timesyncd.service',self.active)
        self.assertNotIn('NetworkManager.service',self.active)
        self.c.wifi(False)
        self.assertTrue(self.c.allowed('time'));self.assertIn('systemd-timesyncd.service',self.active)
        state.write_text('{"internet":true}')
        with self.assertRaises(m.ServiceError):self.c.time(True)

    def test_usb_only_network_time_obeys_selected_modules_and_developer_policy(self):
        p=self.c.storage/'.config/slot/features-v1';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('slot-features-v1\nemulator-mgba\nusb-network\nssh\nnetwork-time\ndeveloper\n')
        self.usb_ready();state=self.c.runtime/'slot-usb-network/state.json';state.parent.mkdir(parents=True)
        state.write_text('{"internet":true,"lease":"192.168.137.2/24"}')
        self.c.set_developer(True)
        self.assertTrue(self.c.allowed('time'));self.assertFalse(self.c.allowed('wifi'))
        self.assertIn('systemd-timesyncd.service',self.active)
        self.assertNotIn('NetworkManager.service',self.active)
        self.c.usb(False);self.assertFalse(self.c.allowed('time'))
        self.assertNotIn('systemd-timesyncd.service',self.active)

    def test_usb_off_leaves_independent_wifi_services_running(self):
        self.c.set_developer(True);self.usb_ready();before=self.active.copy();self.c.usb(False)
        self.assertEqual(self.active,before)
        self.assertTrue(all(self.c.allowed(f) for f in m.FEATURES));self.assertFalse(self.c.allowed('usb'))

    def test_invalid_feature_cannot_prepare_network(self):
        with self.assertRaises(m.ServiceError):self.c.prepare('../ssh')
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
