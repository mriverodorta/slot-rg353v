#!/usr/bin/env python3
"""Expand a saved boot profile into additive milliseconds and explicit gaps."""
import argparse
import csv
import io
import json
from pathlib import Path
import re


def partition(start, end, children):
    if not 0 <= start <= end:
        raise ValueError('Invalid parent interval')
    result = []
    cursor = start
    for row in sorted(children, key=lambda x: (x['start_s'], x['end_s'])):
        a, b = row['start_s'], row['end_s']
        if a < start - 1e-6 or b > end + 1e-6 or b < a:
            raise ValueError('Child interval outside parent: ' + row['name'])
        if a < cursor - 1e-6:
            raise ValueError('Overlapping children cannot be added: ' + row['name'])
        if a > cursor:
            result.append({'name': 'Other work / transition / probe overhead', 'start_s': cursor, 'end_s': a, 'kind': 'unattributed'})
        result.append({**row, 'kind': row.get('kind', 'measured_span')})
        cursor = b
    if cursor < end:
        result.append({'name': 'Other work / transition / probe overhead', 'start_s': cursor, 'end_s': end, 'kind': 'unattributed'})
    for row in result:
        row['duration_ms'] = (row['end_s'] - row['start_s']) * 1000
    return result


def critical_path(report):
    main = report['summary']['stages'][2]
    start, end = main['start_s'], main['end_s']
    if start is None or end is None:
        raise ValueError('Missing service-stage boundary')
    names = re.findall(r'([A-Za-z0-9_.@:-]+\.(?:service|target|socket|mount|slice))\s+@', report.get('critical_chain', ''))
    if not names or names[0] != 'slot-rg353v.service':
        raise ValueError('Missing native Slot critical chain')
    units = {u['Id']: u for u in report['summary']['units']}
    children = []
    cursor = start
    for name in reversed(names[1:]):
        if name not in units and name.endswith('.slice'):
            # The original collector omits slice objects; keep their time as an explicit gap.
            continue
        if name not in units:
            raise ValueError('Missing chain unit: ' + name)
        unit = units[name]
        b = unit['end_s']
        if b is None:
            raise ValueError('Chain unit has no ready timestamp: ' + name)
        b = min(b, end)
        if b <= cursor:
            continue
        a = max(cursor, unit['start_s'] if unit['start_s'] is not None else b)
        if a < b:
            children.append({'name': name, 'start_s': a, 'end_s': b, 'kind': 'exposed_activation'})
        cursor = b
    return partition(start, end, children)


def expand(report):
    stages = report['summary']['stages']
    output = {'schema': 1, 'boot_id': report['boot_id'], 'clock': report['clock'],
              'notes': ['Unit wall times overlap; only the critical-path partition is additive.',
                        'Transitions are elapsed gaps, not proven CPU idle time.',
                        'Frontend intervals are named by the completion marker and can include preceding splash refreshes.',
                        'A unit activation or script span includes CPU, I/O and waits; it is not exclusive CPU time.'],
              'service_path': critical_path(report)}
    init = [x for x in report['summary']['init_steps'] if x['name'].startswith('init-') and x['duration_s'] is not None]
    output['initramfs'] = partition(stages[1]['start_s'], stages[1]['end_s'], init)
    units = {u['Id']: u for u in report['summary']['units']}
    hardware = units['rocknix-autostart.service']
    spans = [x for x in report['summary']['init_steps'] if x['name'].startswith('hardware-') and x['duration_s'] is not None]
    automount = units.get('rocknix-automount.service', {})
    if (automount.get('start_s') is not None and automount.get('end_s') is not None
        and hardware['start_s'] <= automount['start_s'] <= automount['end_s'] <= hardware['end_s']
        and not any(x['start_s'] < automount['end_s'] and automount['start_s'] < x['end_s'] for x in spans)):
        spans.append({'name': 'rocknix-automount.service (synchronous hardware-startup wait)', 'start_s': automount['start_s'], 'end_s': automount['end_s']})
    output['hardware_scripts'] = partition(hardware['start_s'], hardware['end_s'], spans)
    output['frontend'] = partition(stages[-1]['start_s'], stages[-1]['end_s'], report['summary']['frontend_steps'])
    return output


def render(data):
    lines = ['# Boot millisecond drilldown', '', 'Boot ID: ' + data['boot_id'], '', *data['notes'], '']
    for group in ('service_path', 'initramfs', 'hardware_scripts', 'frontend'):
        rows = data[group]
        total = sum(x['duration_ms'] for x in rows)
        lines += ['## ' + group.replace('_', ' ') + f' — {total:.3f} ms', '',
                  '| Work | Kernel-relative start ms | End ms | Elapsed ms | Classification |', '|---|---:|---:|---:|---|']
        for x in rows:
            lines.append(f"| {x['name']} | {x['start_s']*1000:.3f} | {x['end_s']*1000:.3f} | {x['duration_ms']:.3f} | {x['kind']} |")
        lines.append('')
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    report = json.loads(args.report.read_text())
    if report.get('clock') != 'CLOCK_MONOTONIC':
        raise ValueError('Unsupported clock')
    data = expand(report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'drilldown.json').write_text(json.dumps(data, indent=2)+'\n')
    (args.output_dir/'drilldown.md').write_text(render(data))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['group','work','start_ms','end_ms','duration_ms','classification'])
    for group in ('service_path','initramfs','hardware_scripts','frontend'):
        for x in data[group]:
            writer.writerow([group,x['name'],x['start_s']*1000,x['end_s']*1000,x['duration_ms'],x['kind']])
    (args.output_dir/'drilldown.csv').write_text(out.getvalue())
    print(json.dumps({'boot_id':data['boot_id'],'folder':str(args.output_dir),'segments':sum(len(data[k]) for k in ('service_path','initramfs','hardware_scripts','frontend'))}))


if __name__ == '__main__':
    main()
