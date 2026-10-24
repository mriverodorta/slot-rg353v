#!/usr/bin/env python3
"""Private installer SSH over Wi-Fi/USB, entirely in RAM before systemd."""
import argparse
import base64
import configparser
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

HERE=Path(__file__).resolve().parent

def command(args,required=True,timeout=20,**kwargs):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,**kwargs)
    if required and p.returncode:raise RuntimeError(Path(args[0]).name+' failed')
    return p

def private(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as out:out.write(data);out.flush()
    path.chmod(0o600)

def wpa_config(profile):
    blocks=['ctrl_interface=/run/slot-setup-access/wpa','update_config=0']
    for entry in profile['wifi']:
        c=configparser.ConfigParser(interpolation=None);c.read_string(base64.b64decode(entry['data']).decode())
        if c.get('ipv4','method',fallback='auto')!='auto' or c.get('wifi-security','key-mgmt',fallback='')!='wpa-psk':continue
        ssid=c.get('wifi','ssid').encode();password=c.get('wifi-security','psk')
        if b'\\' in ssid or not 1<=len(ssid)<=32:continue
        if re.fullmatch('[0-9a-fA-F]{64}',password):psk=password
        elif 8<=len(password.encode())<=63:psk=hashlib.pbkdf2_hmac('sha1',password.encode(),ssid,4096,32).hex()
        else:continue
        blocks.extend(['network={','ssid='+ssid.hex(),'psk='+psk,'key_mgmt=WPA-PSK','}'])
    if len(blocks)==2:raise ValueError('No supported saved Wi-Fi profile')
    return '\n'.join(blocks)+'\n'

def firmware_path(init_root=Path('/proc/1/root')):
    relative=Path('usr/lib/kernel-overlays/base/lib/firmware')
    # Firmware loading resolves paths from PID 1's root. During the RAM
    # installer SYSTEM is still at /sysroot, outside this Python chroot.
    if (init_root/'sysroot'/relative).is_dir():return '/sysroot/'+str(relative)
    if (init_root/relative).is_dir():return '/'+str(relative)
    raise ValueError('Kernel firmware source is unavailable')

class Access:
    def __init__(self,profile,host,expected,runtime=Path('/run/slot-setup-access')):
        self.profile=profile;self.host=Path(host);self.expected=expected;self.runtime=Path(runtime)
        self.children=[];self.mounts=[];self.usb=None;self.stop=threading.Event();self.wifi=None;self.firmware_before=None;self.status_lock=threading.Lock()

    def status(self,**values):
        with self.status_lock:
            path=self.runtime/'status.json'
            try:state=json.loads(path.read_text())
            except FileNotFoundError:state={}
            state.update(values);tmp=self.runtime/'status.new';tmp.write_text(json.dumps(state));os.replace(tmp,path)

    def spawn(self,args,name):
        if self.stop.is_set():raise InterruptedError('Setup debugging stopped')
        with (self.runtime/(name+'.log')).open('a') as log:
            p=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        self.children.append(p);return p

    def prepare_ram(self):
        for name in ('storage','var'):
            path=Path('/')/name
            if path.is_mount() or any(path.iterdir()):raise ValueError('Installer RAM target is already in use')
            command(['mount','-t','tmpfs','-o','mode='+('0700' if name=='storage' else '0755')+',size=16m','tmpfs',str(path)])
            self.mounts.append(path)
        private(Path('/storage/.cache/shadow'),Path('/usr/cache/shadow').read_bytes())
        private(Path('/storage/.cache/systemd-machine-id'),(hashlib.sha256(('slot-setup-usb:'+self.expected).encode()).hexdigest()[:32]+'\n').encode())
        Path('/var/empty').mkdir(mode=0o755)

    def prepare_ssh(self,port=22):
        if hashlib.sha256(self.host.read_bytes()).hexdigest()!=self.expected:raise ValueError('Setup host key differs')
        self.runtime.mkdir(mode=0o700,parents=True,exist_ok=True);self.runtime.chmod(0o700)
        private(self.runtime/'host-key',self.host.read_bytes())
        private(self.runtime/'authorized_keys',('\n'.join(self.profile['authorized_keys'])+'\n').encode())
        if not self.profile['authorized_keys']:raise ValueError('Setup SSH needs an authorized public key')
        config='\n'.join([
            'Port '+str(port),'HostKey '+str(self.runtime/'host-key'),
            'AuthorizedKeysFile '+str(self.runtime/'authorized_keys'),
            'PidFile '+str(self.runtime/'sshd.pid'),'PermitRootLogin prohibit-password',
            'PasswordAuthentication no','KbdInteractiveAuthentication no','AuthenticationMethods publickey',
            'UseDNS no','StrictModes yes','AllowUsers root',
            'AllowTcpForwarding no','AllowAgentForwarding no','X11Forwarding no',
            'Subsystem sftp internal-sftp','LogLevel ERROR','',
        ])
        private(self.runtime/'sshd.conf',config.encode())
        command(['/usr/sbin/sshd','-t','-f',str(self.runtime/'sshd.conf')])
        return self.spawn(['/usr/sbin/sshd','-D','-e','-f',str(self.runtime/'sshd.conf')],'sshd')

    def wifi_status(self):
        if not (self.runtime/'wpa'/self.wifi).exists():return ''
        # wpa_cli otherwise binds its client socket under read-only /tmp.
        return command(['/usr/bin/slot-wpa-cli','-p',str(self.runtime/'wpa'),
                        '-s',str(self.runtime),'-i',self.wifi,'status']).stdout

    def start_wifi(self):
        private(self.runtime/'wpa.conf',wpa_config(self.profile).encode())
        firmware=Path('/sys/module/firmware_class/parameters/path')
        if firmware.exists():
            self.firmware_before=firmware.read_text();firmware.write_text(firmware_path())
        command(['rfkill','unblock','wlan'])
        command(['modprobe','-d','/usr/lib/kernel-overlays/base','rtw88_8821cs'])
        for _ in range(100):
            names=[p.name for p in Path('/sys/class/net').glob('*') if (p/'device/driver').resolve().name=='rtw88_8821cs']
            if names:break
            if self.stop.wait(.1):return
        if len(names)!=1:raise ValueError('Setup Wi-Fi adapter is unavailable')
        self.wifi=names[0];command(['ip','link','set','dev',self.wifi,'up'])
        (self.runtime/'wpa').mkdir(exist_ok=True)
        self.spawn(['/usr/lib/slot/wpa_supplicant','-D','nl80211','-i',self.wifi,'-c',str(self.runtime/'wpa.conf')],'wifi')
        for _ in range(60):
            if self.stop.wait(.5):return
            if 'wpa_state=COMPLETED' in self.wifi_status():break
        else:raise ValueError('Saved Wi-Fi did not connect during setup')
        script=self.runtime/'dhcp.sh'
        script.write_text('''#!/bin/sh
case "$1" in
 deconfig) ip -4 address flush dev "$interface";;
 bound|renew) ip -4 address flush dev "$interface"; ip address add "$ip/${mask:-24}" dev "$interface"; ip link set dev "$interface" up;;
esac
''');script.chmod(0o700)
        self.spawn(['/usr/sbin/udhcpc','-f','-i',self.wifi,'-s',str(script),'-p',str(self.runtime/'udhcpc.pid'),'-t','5','-T','3'],'dhcp')

    def start_usb(self):
        config=Path('/sys/kernel/config')
        if not config.is_mount():
            command(['mount','-t','configfs','configfs',str(config)]);self.mounts.append(config)
        # Built-in functions need no load; modular builds use the base overlay.
        command(['modprobe','-d','/usr/lib/kernel-overlays/base','usb_f_ecm'],required=False)
        source='/usr/bin/slot-usb-network';loader=importlib.machinery.SourceFileLoader('setup_usb',source)
        spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
        def execute(args):
            if self.stop.is_set() and args[:2]!=['/usr/bin/slot-services','usb']:raise InterruptedError('Setup debugging stopped')
            if args and args[0]=='/usr/bin/slot-services':return subprocess.CompletedProcess(args,0,'','')
            return module.execute(args)
        self.usb=module.Controller(run=execute)
        with self.usb.locked():self.usb.setup()
        self.spawn(['/usr/sbin/udhcpd','-f','/run/slot-usb-network/udhcpd.conf'],'usb-dhcp')
        self.status(usb='172.31.53.1')

    def network(self,name,method):
        try:method()
        except Exception as error:self.status(**{name+'_error':str(error)})

    def close(self):
        self.stop.set()
        for child in reversed(self.children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=4)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=4)
        if self.usb:
            with contextlib.suppress(Exception):
                with self.usb.locked():self.usb.cleanup()
        if self.firmware_before is not None:
            Path('/sys/module/firmware_class/parameters/path').write_text(self.firmware_before);self.firmware_before=None
        if self.wifi:command(['ip','-4','address','flush','dev',self.wifi],required=False)
        for path in reversed(self.mounts):command(['umount',str(path)],required=False)

    def addresses(self):
        if not self.wifi:return []
        result=command(['ip','-o','-4','address','show','dev',self.wifi],required=False)
        return re.findall(r'\binet ([0-9.]+)/',result.stdout) if result.returncode==0 else []

    def run(self):
        self.runtime.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.prepare_ram();self.prepare_ssh();self.status(ssh=True)
        workers=[threading.Thread(target=self.network,args=(name,method),daemon=True) for name,method in [('wifi',self.start_wifi),('usb',self.start_usb)]]
        for worker in workers:worker.start()
        try:
            while not self.stop.wait(.5):
                if self.wifi:
                    addresses=self.addresses()
                    if addresses:self.status(wifi=addresses[0])
        finally:
            self.stop.set()
            for worker in workers:worker.join(timeout=35)

def guard():
    if Path('/proc/1/comm').read_text().strip() not in ('init','busybox'):raise ValueError('Setup access runs before systemd')
    if b'anbernic,rg353v' not in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0'):raise ValueError('Wrong hardware')
    for node in Path('/sys/class/block').glob('mmcblk*'):
        if (node/'device/type').exists() and (node/'device/type').read_text().strip()=='MMC':
            if (node/'ro').read_text().strip()!='1':raise ValueError('eMMC protection is required')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--host-key',type=Path,required=True);p.add_argument('--host-sha256',required=True);a=p.parse_args()
    guard();spec=importlib.util.spec_from_file_location('debug',HERE/'slot-setup-debug.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    profile=d.load(a.profile)
    if profile is None:raise ValueError('Private setup profile is missing')
    access=Access(profile,a.host_key,a.host_sha256)
    signal.signal(signal.SIGTERM,lambda *_:access.stop.set())
    signal.signal(signal.SIGINT,lambda *_:access.stop.set())
    try:access.run()
    finally:access.close()

if __name__=='__main__':main()
