#!/usr/bin/env python3
"""Capture a read-only, low-frequency RG353V runtime baseline over SSH."""
import argparse, datetime, json, os, pathlib, re, statistics, subprocess
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('host', help='root@handheld-IP')
p.add_argument('--label', default='shelf')
p.add_argument('--seconds', type=int, default=60)
p.add_argument('--interval', type=int, default=2)
p.add_argument('--key', default=os.environ.get('SLOT_SSH_KEY'))
a = p.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9_.@:-]+', a.host) or a.host.startswith('-'): p.error('Invalid host')
if not re.fullmatch(r'[a-zA-Z0-9_-]+', a.label): p.error('Use a simple label')
if not 2 <= a.interval <= 30 or not a.interval <= a.seconds <= 600: p.error('Duration must be interval..600 seconds; interval 2..30')
root = pathlib.Path(__file__).resolve().parents[1]
out = root/'local-logs'/'profiles'/(datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+a.label)
out.mkdir(parents=True)
ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5']
if a.key: ssh += ['-i', a.key, '-o', 'IdentitiesOnly=yes']
script = (root/'ports/rg353v/profile-runtime.sh').read_bytes()
with (out/'raw.txt').open('wb') as f:
    result = subprocess.run(ssh+[a.host, 'sh -s -- %d %d' % (a.seconds//a.interval, a.interval)], input=script, stdout=f)
if result.returncode: raise SystemExit('SSH capture failed; no baseline established.')
raw = (out/'raw.txt').read_text()
samples = []
for block in raw.split('SAMPLE\n')[1:]:
    item = {'sys': {}}
    for line in block.splitlines():
        if line.startswith('UPTIME '): item['time'] = float(line.split()[1])
        elif line.startswith('CPU '): item['cpu'] = list(map(int, line.split()[2:10]))
        elif line.startswith('PID '): item['pid'] = int(line.split()[1])
        elif line.startswith('TICKS '): item['ticks'] = int(line.split()[1])
        elif line.startswith('SYS '):
            _, path, value = line.split(); item['sys'][path] = int(value)
        else:
            match = re.match(r'(\w+):\s+(\d+) kB', line)
            if match: item[match[1]] = int(match[2])
    samples.append(item)
meta = raw.split('META\n',1)[1].split('ENDMETA',1)[0].splitlines()
hz = int(meta[1])
load, slot = [], []
for before, after in zip(samples, samples[1:]):
    delta = [b-a for a,b in zip(before['cpu'], after['cpu'])]
    if sum(delta)>0: load.append(100*(sum(delta)-delta[3]-delta[4])/sum(delta))
    if before['pid']==after['pid'] and 'ticks' in before and 'ticks' in after:
        slot.append(100*(after['ticks']-before['ticks'])/hz/(after['time']-before['time']))
def stats(values):
    return None if not values else {'min':round(min(values),2),'mean':round(statistics.mean(values),2),'max':round(max(values),2)}
summary = {'label':a.label, 'samples':len(samples), 'memory_MiB':{k:stats([s[k]/1024 for s in samples if k in s]) for k in ['MemTotal','MemAvailable','VmRSS','Pss','VmSwap','SwapFree']}, 'system_cpu_percent':stats(load), 'slot_cpu_percent_one_core_100':stats(slot), 'sensors':{k:stats([s['sys'][k] for s in samples if k in s['sys']]) for k in sorted({k for s in samples for k in s['sys']})}, 'notes':['System CPU is normalized across all cores; Slot CPU can exceed 100%.','Frequency values are kHz; thermal values are millidegrees Celsius.','CPU load does not measure game FPS. Raw capture includes memory pressure and paging counters.']}
(out/'samples.json').write_text(json.dumps(samples,indent=2)+'\n')
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2)); print('Saved:',out)
