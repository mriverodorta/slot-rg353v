#!/usr/bin/env python3
"""Compile the shared progress plan; invalid dependencies fail the image build."""
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text())
assert plan['schema'] == 1
ids = [s['id'] for s in plan['services']]
assert len(set(ids)) == len(ids)
rows = []
for i, service in enumerate(plan['services']):
    after = ids.index(service['after']) if service.get('after') else -1
    assert after < i and 0 < len(service['units']) <= 8
    rows.append('{' + json.dumps(service['id']) + ',{' + ','.join(map(json.dumps, service['units'])) + ',NULL},' +
                ('true' if service.get('optional', False) else 'false') + ',' + str(after) + '}')
Path(sys.argv[2]).write_text('/* Generated from the shared boot plan. */\n'
    'static const struct { const char *id; const char *units[9]; bool optional; int after; } services[]={\n' +
    ',\n'.join(rows) + '\n};\n#define SERVICE_COUNT (sizeof(services)/sizeof(services[0]))\n' +
    '#define INIT_COUNT ' + str(len(plan['init'])) + 'u\n#define FRONTEND_COUNT ' + str(len(plan['frontend'])) + 'u\n')
