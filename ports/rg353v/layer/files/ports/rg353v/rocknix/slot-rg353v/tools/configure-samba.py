#!/usr/bin/env python3
"""Provision the share in image defaults without rewriting user configuration."""
from pathlib import Path
import re
import sys


def configure(text, share):
    if not re.search(r'^\s*\[global\]\s*$', text, re.MULTILINE | re.IGNORECASE):
        raise ValueError('ROCKNIX Samba defaults changed; review the Slot share')
    if re.search(r'^\s*\[slot\]\s*$', text, re.MULTILINE | re.IGNORECASE):
        return text
    return text.rstrip() + '\n' + share


if __name__ == '__main__':
    target, share = map(Path, sys.argv[1:])
    target.write_text(configure(target.read_text(), share.read_text()))
