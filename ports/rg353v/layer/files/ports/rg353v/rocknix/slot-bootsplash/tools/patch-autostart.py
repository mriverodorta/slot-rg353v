#!/usr/bin/env python3
"""Instrument the installed RG353V autostart script, preserving upstream commands."""
from pathlib import Path
import sys


def patch(text):
    if '# Slot boot profiler hardware spans' in text:
        return text
    lines = text.splitlines(keepends=True)
    found = 0
    result = []
    for line in lines:
        if line.strip() in ('"${script}" 2>&1 >>${BOOTLOG}', '${script} 2>&1 >>${BOOTLOG}'):
            indent = line[:len(line)-len(line.lstrip())]
            if found >= 5:
                raise ValueError('Official autostart script invocations changed; review boot profiler spans')
            group = ('platform', 'quirks', 'common', 'device', 'custom')[found]
            result += [indent + '# Slot boot profiler hardware spans\n',
                       indent + '[ ! -x /usr/bin/slot-splash ] || /usr/bin/slot-splash --begin "hardware-' + group + '-${script##*/}" || :\n',
                       line,
                       indent + '[ ! -x /usr/bin/slot-splash ] || /usr/bin/slot-splash --event "hardware-' + group + '-${script##*/}" || :\n']
            found += 1
        else:
            result.append(line)
    if found != 5:
        raise ValueError('Official autostart script invocations changed; review boot profiler spans')
    return ''.join(result)


if __name__ == '__main__':
    target = Path(sys.argv[1])
    target.write_text(patch(target.read_text()))
