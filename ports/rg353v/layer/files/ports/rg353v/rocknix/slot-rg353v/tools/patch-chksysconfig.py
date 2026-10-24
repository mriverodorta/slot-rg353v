#!/usr/bin/env python3
"""Adapt only the official RetroArch presence check for the Slot-only image."""
from pathlib import Path
import sys

MARKER = '  # Slot-only image: RetroArch configs are intentionally absent.\n'
OLD = '''  if [ ! -s /storage/.config/retroarch/retroarch-core-options.cfg ] || \\
     [ ! -s /storage/.config/retroarch/retroarch.cfg ] || \\
     ! grep -q system.hostname /storage/.config/system/configs/system.cfg; then'''
NEW = '  if ! grep -q system.hostname /storage/.config/system/configs/system.cfg; then'


def patch(text):
    if MARKER in text and NEW in text:
        return text
    if text.count(OLD) != 1:
        raise ValueError('ROCKNIX config check changed; review the Slot-only adaptation')
    return text.replace(OLD, MARKER + NEW)


if __name__ == '__main__':
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text()))
