#!/usr/bin/env python3
"""Exercise the Slot adaptation without touching real system configuration."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'ports/rg353v/rocknix/slot-rg353v'
spec = importlib.util.spec_from_file_location('patcher', PACKAGE / 'tools/patch-chksysconfig.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
original = (PACKAGE / 'tests/chksysconfig.fixture').read_text()
patched = p.patch(original)
assert p.patch(patched) == patched
try:
    p.patch(original.replace('retroarch.cfg', 'future-config.cfg'))
except ValueError:
    pass
else:
    raise AssertionError('Changed upstream checks must require review')
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    config = root / 'storage/.config/system/configs/system.cfg'
    config.parent.mkdir(parents=True)
    tools = root / 'bin'
    tools.mkdir()
    rsync = tools / 'rsync'
    rsync.write_text('#!/bin/sh\ntouch "$RESTORE_MARKER"\n')
    rsync.chmod(0o755)
    script = root / 'chksysconfig'
    script.write_text(patched.replace('. /etc/profile', ': # isolated test environment')
                      .replace('/storage', str(root / 'storage'))
                      .replace('/usr/config', str(root / 'defaults')))
    marker = root / 'restore-called'
    env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'], RESTORE_MARKER=str(marker))
    config.write_text('system.hostname=RG353V\nwifi.enabled=0\n')
    subprocess.run(['bash', str(script), 'verify'], env=env, check=True)
    assert not marker.exists(), 'Absent RetroArch must not reset a valid Slot configuration'
    assert 'wifi.enabled=0' in config.read_text()
    config.write_text('wifi.enabled=0\n')
    subprocess.run(['bash', str(script), 'verify'], env=env, check=True)
    assert marker.exists(), 'Missing core configuration must still trigger upstream recovery'
print('PASS valid Slot settings survive missing RetroArch, recovery remains, patch is idempotent and rejects drift')

spec = importlib.util.spec_from_file_location('samba', PACKAGE / 'tools/configure-samba.py')
samba = importlib.util.module_from_spec(spec)
spec.loader.exec_module(samba)
share = (PACKAGE / 'config/slot-share.conf').read_text()
defaults = '[global]\n  server string = Custom name\n\n[Other]\n  path = /other\n'
configured = samba.configure(defaults, share)
assert configured.startswith(defaults.rstrip())
assert configured.count('[Slot]') == 1
assert samba.configure(configured, share) == configured
custom = defaults + '\n [sLoT] \n  path = /custom\n  guest ok = no\n'
assert samba.configure(custom, share) == custom
try:
    samba.configure('[unexpected]\n', share)
except ValueError:
    pass
else:
    raise AssertionError('Changed Samba defaults must require review')
print('PASS Samba defaults retain other shares and existing Slot customization without a repair hook')

spec = importlib.util.spec_from_file_location('input_startup', PACKAGE / 'tools/patch-input-autostart.py')
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)
original = (PACKAGE / 'tests/deviceutils.fixture').read_text()
patched = startup.patch(original)
assert startup.patch(patched) == patched
try:
    startup.patch(original.replace('start input &', 'start future-input &'))
except ValueError:
    pass
else:
    raise AssertionError('Changed input startup must require review')
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    tools = root / 'bin'
    tools.mkdir()
    mock = tools / 'systemctl'
    mock.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$INPUT_STARTUP_LOG"\n')
    mock.chmod(0o755)
    results = {}
    for enabled in ['true', 'false']:
        for name, text in [('original', original), ('slot', patched)]:
            script = root / (name + '.sh')
            script.write_text(text.replace('. /etc/profile', ': # isolated test environment') + '\nwait\n')
            log = root / (name + enabled + '.log')
            env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'], INPUT_STARTUP_LOG=str(log),
                       DEVICE_HAS_FAN=enabled, DEVICE_FAKE_JACKSENSE=enabled,
                       DEVICE_HAS_HDMI=enabled, DEVICE_BATTERY_LED_STATUS=enabled)
            subprocess.run(['bash', '-c', 'tocon() { :; }; export -f tocon; exec bash "$1"',
                            'test', str(script)], env=env, check=True)
            results[name] = sorted(log.read_text().splitlines())
        assert results['slot'] == [line for line in results['original'] if line != 'start input']
print('PASS input autostart ownership preserves peripheral startup and rejects upstream drift')
