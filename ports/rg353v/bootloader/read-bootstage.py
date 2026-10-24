#!/usr/bin/env python3
"""Read U-Boot's FDT timing export without treating its timer as button time."""
import argparse
import json
import os
from pathlib import Path
import struct


def sd_probe(row):
    fields = dict(part.split('=', 1) for part in row['name'].split(';')[1:])
    for key in ('bus_width', 'requested_hz', 'provider_hz', 'fixed_divider', 'divider', 'ctype',
                'signal_voltage_enum', 'fifo_mode', 'dma64', 'ddr',
                'config_max_hz', 'max_blocks', 'card_caps', 'host_caps'):
        fields[key] = int(fields[key])
    rate = fields['provider_hz']
    if not 0 < rate <= 1_000_000_000 or not 0 <= fields['divider'] <= 255:
        raise ValueError('Invalid SD clock provider result or divider')
    if fields['fixed_divider'] != 2:
        raise ValueError('Unexpected Rockchip clock-generator divider')
    divisor = fields['fixed_divider'] * (2 * fields['divider'] if fields['divider'] else 1)
    fields['card_clock_hz_derived'] = rate / divisor
    fields['theoretical_payload_MB_s'] = fields['card_clock_hz_derived'] * fields['bus_width'] * (2 if fields['ddr'] else 1) / 8e6
    fields['transfer_path'] = 'FIFO / PIO' if fields['fifo_mode'] else 'IDMAC DMA'
    fields['sample_us'] = row['us']
    fields['epoch'] = row['epoch']
    return fields


def read_report(root, boot_id):
    if not root.is_dir():
        raise ValueError('No BOOTSTAGE device-tree export is present')
    records = []
    for node in sorted((p for p in root.iterdir() if p.is_dir()),
                       key=lambda p: int(p.name), reverse=True):
        name = (node / 'name').read_bytes().rstrip(b'\0').decode('utf-8')
        fields = [key for key in ('mark', 'accum') if (node / key).exists()]
        if len(fields) != 1:
            raise ValueError(f'{node.name}: expected one timing field')
        raw = (node / fields[0]).read_bytes()
        if len(raw) != 4:
            raise ValueError(f'{node.name}: expected a 32-bit big-endian timing')
        records.append({'name': name, 'kind': fields[0],
                        'us': struct.unpack('>I', raw)[0],
                        'synthetic_origin': name == 'reset'})
    marks = [r for r in records if r['kind'] == 'mark' and not r['synthetic_origin']]
    monotonic = all(a['us'] <= b['us'] for a, b in zip(marks, marks[1:]))
    epochs = []
    for row in marks:
        if not epochs or row['us'] < epochs[-1]['marks'][-1]['us']:
            epochs.append({'marks': []})
        row['epoch'] = len(epochs) - 1
        epochs[-1]['marks'].append(row)
    pending = {}
    spans = []
    filename = None
    for row in marks:
        name = row['name']
        if name.startswith('/'):
            filename = name
        if name.endswith('-start'):
            pending[name[:-6]] = (row['us'], row['epoch'], filename if name == 'slot-file-read-start' else None)
        elif name.endswith('-end') and name[:-4] in pending:
            start, epoch, file = pending.pop(name[:-4])
            if row['us'] < start or row['epoch'] != epoch:
                raise ValueError('Boot timer moved backwards within a measured operation')
            spans.append({'name': name[:-4], 'file': file, 'epoch': epoch, 'start_us': start,
                          'end_us': row['us'], 'duration_us': row['us'] - start})
    return {'schema': 1, 'boot_id': boot_id,
            'clock': 'U-Boot timer_get_boot_us / ARM physical counter; origin not calibrated to Power button',
            'monotonic_marks': monotonic, 'records': records, 'epochs': epochs, 'operation_spans': spans,
            'sd_snapshots': [sd_probe(r) for r in marks if r['name'].startswith('slot-sd-probe;')],
            'limitations': ['The reset=0 record is synthetic, not a measured button press.',
                            'Boot ROM and proprietary DDR firmware have no internal markers. SPL dram_init is later RAM setup, not DDR training.',
                            'A backwards timestamp creates a separate epoch; its gap is unmeasured.',
                            'Operation spans may nest; do not sum them as independent stages.',
                            'Linux CLOCK_MONOTONIC has a separate origin; handoff cleanup and entry gap are not measured by this export.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/sys/firmware/devicetree/base/bootstage'))
    parser.add_argument('--boot-id-file', type=Path, default=Path('/proc/sys/kernel/random/boot_id'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--save-dir', type=Path)
    args = parser.parse_args()
    report = read_report(args.root, args.boot_id_file.read_text().strip())
    data = json.dumps(report, indent=2) + '\n'
    if args.save_dir:
        import uuid
        boot = str(uuid.UUID(report['boot_id']))
        args.save_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = args.save_dir / ('boot-' + boot + '.json')
        temporary = target.with_suffix('.tmp')
        with temporary.open('w') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(target)
        reports = sorted(args.save_dir.glob('boot-*.json'), key=lambda p: p.stat().st_mtime)
        for old in reports[:-10]:
            old.unlink()
        print(str(target))
        raise SystemExit(0)
    if args.output:
        args.output.write_text(data)
    else:
        print(data, end='')
