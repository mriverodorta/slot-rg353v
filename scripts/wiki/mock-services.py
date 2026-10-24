#!/usr/bin/env python3
"""Documentation-only fixtures. Run inside the disposable capture container.

These responses illustrate menus; they do not contact a handheld or a network.
Never install this file in firmware. All addresses and names are examples.
"""
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'nmcli':
    joined = ' '.join(args)
    if args == ['radio', 'wifi']:
        print('enabled')
    elif 'DEVICE,TYPE,STATE' in joined:
        print('wlan0:wifi:connected')
    elif 'GENERAL.CON-UUID' in joined:
        print('documentation-example')
    elif '802-11-wireless.ssid' in joined:
        print('Home Wi-Fi')
    elif 'IP4.ADDRESS' in joined:
        print('192.0.2.2/24')
    elif 'IN-USE,BSSID,SSID,SIGNAL,SECURITY' in joined:
        print('*:02\\:00\\:00\\:00\\:00\\:01:Home Wi-Fi:90:WPA2')
        print(':02\\:00\\:00\\:00\\:00\\:02:Guest Wi-Fi:75:WPA2')
    elif 'device status' in joined:
        print('wlan0:wifi:connected')
    elif 'GENERAL.STATE' in joined:
        print('100 (connected)')
    sys.exit(0)

data = {'protocol': '1'}
if name == 'slot-sharing-ui':
    data.update(enabled='1', state='Running', address='smb://192.0.2.2/Slot', access='Guest')
elif name == 'slot-ssh-ui':
    data.update(enabled='1', state='Running', address='ssh root@192.0.2.2', password='Set', count='0')
elif name == 'slot-usb-network':
    data.update(protocol='2', enabled='1', legacy='0', internet='0', state='Connected',
                address='192.0.2.2', peer='192.0.2.1', ssh='ssh root@192.0.2.2')
elif name == 'slot-sd-library':
    choice = Path('/tmp/slot-doc-save-location')
    if args and args[0] == 'ui-save-location':
        assert len(args) == 2 and args[1] in ('system', 'game')
        choice.write_text(args[1].title())
    data['save_location'] = choice.read_text() if choice.exists() else 'System'
    data.update(state_0='Mounted', action_0='eject', token_0='example-tf1',
                state_1='Not inserted', action_1='', token_1='')
elif name == 'slot-diagnostics-ui':
    data.update(ip='192.0.2.2', ram='Example: 1.4 GiB', free='Example: 20 GiB', failed='0',
                slot='RG353V', os='RG353V', kernel='7.0.2', profile='Handheld',
                source_slot='868631d7b131', source_os='c445081a5951', layer='See release manifest',
                **{'slot-rg353v': 'active', 'storage-slotcontent': 'active',
                   'NetworkManager': 'active', 'slot-wpa-supplicant': 'active',
                   'slot-wifi-probe-recovery': 'inactive', 'slot-sharing': 'active', 'sshd': 'active'})
elif name == 'slot-ota-ui':
    data.update(event='up-to-date', busy='0', installed='0', downloaded='0', retained='0',
                slot='Example version', os='Example system', source='github.com')
    phase = Path('/tmp/slot-doc-ota-phase')
    phase = phase.read_text().strip() if phase.exists() else ''
    if phase in ('waiting', 'paused', 'health'):
        data.update(session='1', session_phase='paused-network' if phase=='paused' else 'awaiting-health' if phase=='health' else 'waiting-network',
                    busy='0' if phase=='paused' else '1', operation='resume', steps='1', seconds='27',
                    event='paused-network' if phase=='paused' else 'waiting-health' if phase=='health' else 'waiting-network')
elif name == 'slot-usb-storage':
    # Never change mounts, gadget state or the host, even on an accidental call.
    pass
else:
    raise SystemExit('Unknown documentation fixture: ' + name)
for key, value in data.items():
    print(key + '\t' + value)
