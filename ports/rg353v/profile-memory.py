#!/usr/bin/env python3
"""Read-only proportional RAM census. No command lines or credentials collected."""
import json, os, pathlib, time

def values(path):
    result = {}
    for line in pathlib.Path(path).read_text().splitlines():
        key, _, value = line.partition(':')
        fields = value.split()
        if fields and fields[0].isdigit(): result[key] = int(fields[0])
    return result

def snapshot():
    processes = []
    for p in pathlib.Path('/proc').iterdir():
        if not p.name.isdigit(): continue
        try:
            status = values(p/'status')
            if 'VmRSS' not in status: continue
            mem = values(p/'smaps_rollup')
            cg = (p/'cgroup').read_text()
            units = [part for line in cg.splitlines() for part in line.split(':',2)[-1].split('/') if part.endswith('.service')]
            unit = units[-1] if units else '(other user processes)'
            if int(p.name) == os.getpid(): unit = '(profiler)'
            processes.append({'pid':int(p.name), 'name':(p/'comm').read_text().strip(), 'service':unit, 'rss_kib':mem.get('Rss',status['VmRSS']), 'pss_kib':mem.get('Pss',0), 'private_kib':mem.get('Private_Clean',0)+mem.get('Private_Dirty',0), 'swap_kib':mem.get('Swap',0)})
        except (OSError, ValueError, IndexError): continue
    return {'uptime_seconds':float(pathlib.Path('/proc/uptime').read_text().split()[0]),'meminfo_kib':values('/proc/meminfo'),'processes':processes,'memory_pressure':pathlib.Path('/proc/pressure/memory').read_text()}
samples=[]
for i in range(5):
    samples.append(snapshot())
    if i<4: time.sleep(2)
print(json.dumps({'sample_count':len(samples),'samples':samples},indent=2))
