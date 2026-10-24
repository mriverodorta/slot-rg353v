#!/usr/bin/env python3
"""Private USB Ethernet configuration, mode ownership and startup isolation."""
import fcntl
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PORT=ROOT/'ports/rg353v/rocknix/slot-rg353v'
loader=importlib.machinery.SourceFileLoader('usbnetwork',str(PORT/'scripts/slot-usb-network'))
spec=importlib.util.spec_from_loader(loader.name,loader);u=importlib.util.module_from_spec(spec);loader.exec_module(u)

class UsbNetwork(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.calls=[];self.addresses='2: wlan0 inet 192.0.2.10/24 scope global wlan0\n'
        self.c=u.Controller(root/'storage',root/'run',root/'sys',self.execute)
        self.c.udc.mkdir(parents=True);(self.c.udc/'state').write_text('not attached\n')
        self.c.root.mkdir(parents=True)
        identity=self.c.storage/'.cache/systemd-machine-id';identity.parent.mkdir(parents=True);identity.write_text('0123456789abcdef0123456789abcdef\n')
    def execute(self,args):
        self.calls.append(args)
        if args[:3]==['ip','address','add']:
            self.assertEqual((self.c.gadget/'UDC').read_text().strip(),u.UDC_NAME)
        return subprocess.CompletedProcess(args,0,self.addresses if args[:2]==['ip','-o'] else '','')
    def fake_configfs(self):
        mkdir=Path.mkdir;write=Path.write_text
        def create(path,*a,**kw):
            result=mkdir(path,*a,**kw)
            if path==self.c.gadget:
                for name in ['strings','configs','functions']:mkdir(path/name)
                write(path/'UDC','')
            elif path==self.c.gadget/'configs/c.1':mkdir(path/'strings')
            elif path.parent==self.c.gadget/'functions':write(path/'ifname','slotusb0\n')
            return result
        def attribute(path,value):
            if path.name=='UDC' and value.strip()==u.UDC_NAME:
                iface=next((self.c.gadget/'functions').glob('*/ifname'))
                write(iface,iface.read_text().replace('%d','0'))
            return write(path,value)
        return patch.object(Path,'mkdir',create),patch.object(Path,'write_text',attribute)
    def setup_gadget(self):
        a,b=self.fake_configfs()
        with a,b:self.c.setup()
    def test_preflight_rejects_storage_other_gadgets_and_subnet_overlap(self):
        self.c.preflight()
        path=self.c.runtime/'slot-usb/active';path.parent.mkdir(parents=True);path.touch()
        with self.assertRaisesRegex(u.NetworkError,'Finish USB storage'):self.c.preflight()
        path.unlink();other=self.c.root/'other';other.mkdir();(other/'UDC').write_text(u.UDC_NAME)
        with self.assertRaisesRegex(u.NetworkError,'Another USB'):self.c.preflight()
        (other/'UDC').write_text('');self.addresses='2: wlan0 inet 172.31.53.25/24 scope global wlan0\n'
        with self.assertRaisesRegex(u.NetworkError,'overlaps'):self.c.preflight()
    def test_shared_storage_lock_prevents_concurrent_modes(self):
        path=self.c.storage/'.cache/slot-usb/lock';path.parent.mkdir(parents=True)
        with path.open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            with self.assertRaisesRegex(u.NetworkError,'Finish USB storage'):
                with self.c.locked():pass
    def test_stable_usb_identities_are_local_unicast_and_distinct(self):
        a=self.c.identity();self.assertEqual(a,self.c.identity());self.assertTrue(a[0].endswith('-net'))
        self.assertEqual(a[1][:2],'02');self.assertEqual(a[2][:2],'06');self.assertNotEqual(a[1],a[2])
    def test_setup_has_one_ncm_interface_and_no_storage_routing_dns_or_wifi(self):
        self.setup_gadget()
        self.assertEqual((self.c.gadget/'UDC').read_text().strip(),u.UDC_NAME)
        for field,value in [('bDeviceClass','0xef'),('bDeviceSubClass','0x02'),('bDeviceProtocol','0x01')]:
            self.assertEqual((self.c.gadget/field).read_text().strip(),value)
        link=self.c.gadget/'configs/c.1'/u.FUNCTION;self.assertTrue(link.is_symlink())
        text=(self.c.work/'udhcpd.conf').read_text()
        self.assertIn('interface slotusb0\n',text);self.assertIn('start '+u.PEER+'\n',text)
        for option in ['option router','option dns','option ntpsrv']:self.assertNotIn(option,text)
        self.assertIn(['/usr/bin/slot-services','usb','on'],self.calls)
        commands=repr(self.calls)
        for forbidden in ['mount','sshd','NetworkManager','rfkill','default','iptables']:self.assertNotIn(forbidden,commands)
        self.assertEqual((self.c.work/'udhcpd.conf').stat().st_mode&0o777,0o600)
    def test_read_only_status_distinguishes_cable_approval_and_connection(self):
        self.assertEqual(self.c.status()['enabled'],'0');self.assertEqual(self.calls,[])
        self.setup_gadget();p=self.c.runtime/'slot-services/usb.on';p.parent.mkdir(parents=True);p.touch();self.calls.clear()
        for state,label in [('not attached','Waiting for cable'),('addressed','Waiting for computer approval'),('configured','Connected'),('suspended','Connected (suspended)')]:
            (self.c.udc/'state').write_text(state);s=self.c.status();self.assertEqual(s['state'],label);self.assertEqual(s['ssh'],'ssh root@'+u.ADDRESS)
        self.assertEqual(self.calls,[])
    def test_unowned_cleanup_does_not_change_services(self):
        self.c.cleanup();self.assertEqual(self.calls,[])
    def internet_gadget(self):
        self.c.configure('internet', True)
        self.setup_gadget()
        return {'interface':'slotusb0','ip':'192.168.137.2','subnet':'255.255.255.0',
                'router':'192.168.137.1','dns':'192.168.137.1'}

    def test_legacy_mode_uses_ecm_and_does_not_start_online_tools(self):
        self.c.configure('legacy',True);self.setup_gadget()
        self.assertTrue((self.c.gadget/'configs/c.1/ecm.slot').is_symlink())
        self.assertFalse((self.c.gadget/'configs/c.1/ncm.slot').exists())
        self.assertNotIn('openssl-config',repr(self.calls))
        self.assertEqual((self.c.gadget/'bDeviceClass').read_text().strip(),'0x02')

    def test_internet_mode_runs_client_and_never_serves_dhcp_to_the_computer(self):
        self.internet_gadget()
        self.assertFalse((self.c.work/'udhcpd.conf').exists())
        self.assertNotIn(['ip','address','add',u.ADDRESS+'/30','dev','slotusb0'],self.calls)
        self.assertIn(['systemctl','start','openssl-config.service'],self.calls)
        with patch.object(u.os,'execv') as execute:
            self.c.serve()
            binary,args=execute.call_args.args
            self.assertEqual(binary,'/usr/sbin/udhcpc')
            self.assertIn('-f',args);self.assertIn('-R',args);self.assertIn(u.DHCP_HOOK,args)
            self.assertNotIn('-q',args)

    def test_direct_mode_serves_dhcp_and_does_not_route_internet(self):
        self.setup_gadget()
        with patch.object(u.os,'execv') as execute:
            self.c.serve();self.assertEqual(execute.call_args.args[0],'/usr/sbin/udhcpd')

    def test_dhcp_renew_and_deconfig_restore_dns_and_only_remove_usb_route(self):
        env=self.internet_gadget()
        original='nameserver 10.10.10.1\n';self.c.resolver.parent.mkdir(parents=True);self.c.resolver.write_text(original)
        for event in ('bound','renew','renew'):
            self.c.dhcp(event,env)
            self.assertEqual(self.c.state()['lease'],'192.168.137.2/24')
            self.assertIn('nameserver 192.168.137.1',self.c.resolver.read_text())
            self.assertEqual(self.c.resolver.stat().st_mode&0o777,0o644)
        self.assertIn(['ip','route','add','default','via','192.168.137.1','dev','slotusb0','metric','600'],self.calls)
        self.c.dhcp('deconfig',env)
        self.assertNotIn('lease',self.c.state());self.assertEqual(self.c.resolver.read_text(),original)
        deletions=[a for a in self.calls if a[:3]==['ip','route','del']]
        self.assertTrue(all(a==['ip','route','del','default','dev','slotusb0','metric','600'] for a in deletions))
        self.assertNotIn('wlan0',repr([a for a in self.calls if a[1:3] in (['route','del'],['address','del'])]))

    def test_dns_replacement_by_wifi_is_not_overwritten_on_deconfig(self):
        env=self.internet_gadget();self.c.dhcp('bound',env)
        external='nameserver 10.10.10.1\n';self.c.resolver.write_text(external)
        self.c.dhcp('deconfig',env);self.assertEqual(self.c.resolver.read_text(),external)

    def test_dns_symlink_is_restored_after_usb_disconnect(self):
        env=self.internet_gadget();original=self.c.runtime/'original-resolv.conf'
        original.write_text('nameserver 10.10.10.1\n');self.c.resolver.parent.mkdir(parents=True)
        self.c.resolver.symlink_to(original)
        self.c.dhcp('bound',env);self.assertFalse(self.c.resolver.is_symlink())
        self.c.dhcp('deconfig',env);self.assertTrue(self.c.resolver.is_symlink())
        self.assertEqual(self.c.resolver.readlink(),original)
        self.assertEqual(original.read_text(),'nameserver 10.10.10.1\n')

    def test_live_status_tracks_dhcp_address_and_waits_for_sharing(self):
        env=self.internet_gadget();flag=self.c.runtime/'slot-services/usb.on';flag.parent.mkdir(parents=True);flag.touch()
        (self.c.udc/'state').write_text('configured')
        self.assertEqual(self.c.status()['address'],'--');self.assertEqual(self.c.status()['state'],'Enable sharing')
        self.c.dhcp('bound',env)
        self.assertEqual(self.c.status()['address'],'192.168.137.2');self.assertEqual(self.c.status()['state'],'Sharing ready')
        self.assertEqual(self.c.status()['ssh'],'ssh root@192.168.137.2')
        self.c.dhcp('deconfig',env);self.assertEqual(self.c.status()['address'],'--')

    def test_dhcp_rejects_bad_gateway_injection_wrong_interface_and_subnet_conflicts(self):
        env=self.internet_gadget();self.calls.clear()
        for update in ({'ip':'$(touch /tmp/wrong)'},{'router':'10.0.0.1'},
                       {'dns':'1.1.1.1;reboot'},{'interface':'wlan0'},{'router':''},
                       {'subnet':'0.0.0.0'},{'ip':'127.0.0.1'},{'dns':''}):
            before=len(self.calls)
            with self.assertRaises(u.NetworkError):self.c.dhcp('bound',{**env,**update})
            self.assertEqual(len(self.calls),before)
        self.addresses='2: wlan0 inet 192.168.137.8/24 scope global wlan0\n'
        with self.assertRaisesRegex(u.NetworkError,'overlaps'):self.c.dhcp('bound',env)
        self.assertFalse(self.c.resolver.exists())

    def test_lease_ownership_is_journaled_before_network_changes(self):
        env=self.internet_gadget();execute=self.c.run
        def check(args):
            if args[:3]==['ip','address','add']:
                state=self.c.state()
                self.assertEqual(state['lease'],'192.168.137.2/24')
                self.assertEqual(state['gateway'],'192.168.137.1')
                self.assertIn('dns_original',state)
            return execute(args)
        self.c.run=check;self.c.dhcp('bound',env)

    def test_failed_route_cleans_up_new_usb_lease_without_touching_resolver(self):
        env=self.internet_gadget();execute=self.c.run
        def fail(args):
            if args[:3]==['ip','route','add']:return subprocess.CompletedProcess(args,1,'','test failure')
            return execute(args)
        self.c.run=fail
        with self.assertRaises(u.NetworkError):self.c.dhcp('bound',env)
        self.assertNotIn('lease',self.c.state());self.assertFalse(self.c.resolver.exists())

    def test_reconnecting_usb_preserves_explicitly_enabled_remote_services(self):
        self.setup_gadget()
        for name in ('ssh','sharing'):
            flag=self.c.runtime/'slot-services'/(name+'.on');flag.parent.mkdir(parents=True,exist_ok=True);flag.touch()
        self.c.configure('internet',True)
        self.assertIn(['/usr/bin/slot-ssh','set','on'],self.calls)
        self.assertIn(['/usr/bin/slot-sharing','set','on'],self.calls)
        self.assertNotIn('NetworkManager',repr(self.calls))

    def test_active_preference_restart_rolls_back_on_failure(self):
        self.setup_gadget();execute=self.c.run
        def fail(args):
            if args[:2]==['systemctl','restart']:
                self.calls.append(args);return subprocess.CompletedProcess(args,1,'','test failure')
            return execute(args)
        self.c.run=fail
        with self.assertRaises(u.NetworkError):self.c.configure('internet',True)
        self.assertFalse(self.c.options()['internet'])
        self.assertEqual(sum(a[:2]==['systemctl','restart'] for a in self.calls),2)

    def test_generic_usb_trigger_guards_both_modes_and_is_idempotent(self):
        root=Path(self.tmp.name)/'image';script=root/'usr/bin/usbgadget';script.parent.mkdir(parents=True);script.write_text('#!/bin/sh\nexit 0\n')
        mount=root/'usr/lib/systemd/system/storage-slotcontent.mount';mount.parent.mkdir(parents=True);mount.write_text('[Unit]\nDescription=content\n')
        tool=PORT/'tools/configure-usb-storage.py'
        import sys
        subprocess.run([sys.executable,str(tool),str(root)],check=True)
        first=script.read_text();subprocess.run([sys.executable,str(tool),str(root)],check=True)
        self.assertEqual(script.read_text(),first)
        self.assertIn('[ ! -e /run/slot-usb/active ] || exit 0',first)
        self.assertIn('[ ! -e /run/slot-usb-network/active ] || exit 0',first)
        self.assertIn('ConditionPathExists=!/run/slot-usb/active',mount.read_text())

    def test_service_is_opt_in_event_driven_and_uses_existing_dhcp_binary(self):
        unit=(PORT/'system.d/slot-usb-network.service').read_text()
        self.assertNotIn('[Install]',unit);self.assertNotIn('WantedBy=',unit);self.assertNotIn('sleep ',unit)
        self.assertIn('ExecStart=/usr/bin/slot-usb-network serve',unit);self.assertIn('ExecStopPost=/usr/bin/slot-usb-network cleanup',unit)
        rules=(PORT/'udev.d/75-slot-usb-network.rules').read_text();self.assertIn('KERNEL=="slotusb*"',rules);self.assertIn('NM_UNMANAGED',rules);self.assertIn('NAME:="slotusb0"',rules)

if __name__=='__main__':unittest.main()
