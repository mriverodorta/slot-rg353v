#!/usr/bin/env python3
"""Keep ROCKNIX peripheral startup without requesting the competing input unit."""
from pathlib import Path
import sys

OLD = 'tocon "Starting input service..."\nnohup systemctl start input &'
NEW = 'tocon "Slot owns button input; legacy handler is available for recovery."\n: # slot-rg353v input ownership'


def patch(text):
    if NEW in text and OLD not in text:
        return text
    if text.count(OLD) != 1:
        raise ValueError('ROCKNIX input startup changed; review Slot ownership')
    return text.replace(OLD, NEW)


if __name__ == '__main__':
    target = Path(sys.argv[1])
    target.write_text(patch(target.read_text()))
