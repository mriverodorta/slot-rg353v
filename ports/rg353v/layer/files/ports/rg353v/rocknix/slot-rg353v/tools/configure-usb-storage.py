#!/usr/bin/env python3
"""Keep generic gadget/mount entry points out of an exclusive Slot USB session."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
p = root / 'usr/bin/usbgadget'
s = p.read_text()
guard = '[ ! -e /run/slot-usb/active ] || exit 0\n'
if guard not in s:
    first, rest = s.split('\n', 1)
    p.write_text(first + '\n' + guard + rest)
guard = '[ ! -e /run/slot-usb-network/active ] || exit 0\n'
if guard not in p.read_text():
    first, rest = p.read_text().split('\n', 1)
    p.write_text(first + '\n' + guard + rest)
unit = root / 'usr/lib/systemd/system/storage-slotcontent.mount'
if unit.exists():
    s = unit.read_text()
    guard = 'ConditionPathExists=!/run/slot-usb/active\n'
    if guard not in s:
        unit.write_text(s.replace('[Unit]\n', '[Unit]\n' + guard, 1))
