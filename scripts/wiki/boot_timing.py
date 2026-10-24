"""Validate and replay the public, sanitized boot presentation trace.

No device access. Times are kernel-relative; GIF boundaries use its 10 ms grid.
The final shelf hold makes the loop readable and is outside the boot interval.
"""
import hashlib
import json


def load_timing(root):
    timing = json.loads((root / 'wiki/media/boot-timing.json').read_text())
    if timing['schema'] != 1:
        raise ValueError('Unsupported boot trace schema')
    plan = json.loads((root / 'ports/rg353v/rocknix/slot-bootsplash/config/boot-plan.json').read_text())
    counts = {name: len(plan[name]) for name in ('init', 'services', 'frontend')}
    if counts != {name: timing['counter'][name] for name in counts}:
        raise ValueError('Boot trace milestone plan differs from the renderer')
    total = sum(counts.values())
    if total != timing['counter']['total']:
        raise ValueError('Wrong boot trace milestone total')
    for name, expected in timing['source']['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Boot trace source changed: ' + name)
    events = timing['events']
    if events[0] != {'at_s': 0.0, 'view': 'black', 'source': 'timeline-origin'}:
        raise ValueError('Boot trace must begin at kernel entry')
    allowed = {100 * n // total for n in range(total + 1)}
    previous_time = -1
    previous_percent = -1
    for event in events:
        if not previous_time < event['at_s'] < 60:
            raise ValueError('Boot trace times must increase')
        previous_time = event['at_s']
        if event['view'] == 'splash':
            percent = event['percent']
            if percent not in allowed or percent < previous_percent:
                raise ValueError('Percentage is not a monotonic milestone count')
            previous_percent = percent
        elif event['view'] not in ('black', 'shelf') or 'percent' in event:
            raise ValueError('Unknown boot view')
    if events[-1]['view'] != 'shelf' or events[-1]['at_s'] != timing['shelf_swap_s']:
        raise ValueError('Missing measured shelf endpoint')
    if events[-2].get('percent') != 100 or events[-2]['at_s'] != timing['complete_frame_s']:
        raise ValueError('Missing captured 100% handoff')
    if not 0 < timing['shelf_swap_s'] - timing['complete_frame_s'] < 0.1:
        raise ValueError('Unexpectedly long 100% handoff; inspect the captured run')
    return timing


def quantized_events(timing):
    """Round absolute boundaries, avoiding accumulated per-frame rounding drift."""
    events = timing['events']
    boundaries = [round(e['at_s'] * 100) * 10 for e in events]
    boundaries.append(boundaries[-1] + timing['shelf_hold_ms'])
    for index, event in enumerate(events):
        duration = boundaries[index + 1] - boundaries[index]
        if duration <= 0:
            raise ValueError('Captured event is shorter than the GIF time grid')
        yield event, duration
