#!/usr/bin/env python3
"""Compose fixed RG353V startup data in the installed image, never upstream sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

STATIC = {
    '001-device_config': 'devices/Anbernic RG353V/001-device_config',
    '002-audio_path': 'devices/Anbernic RG353V/050-audio_path',
    '020-gpios': 'devices/Anbernic RG353V/020-gpios',
    '002-turbo-mode_config': 'platforms/RK3566/002-turbo-mode_config',
    '010-governors': 'platforms/RK3566/010-governors',
    '010-led_control': 'platforms/RK3566/010-led_control',
    '015-rk817_config': 'platforms/RK3566/015-rk817_config',
    '050-modifiers': 'platforms/RK3566/050-modifiers',
}
DEFERRED = ('network-base.service', 'network-online.service', 'NetworkManager.service', 'slot-wpa-supplicant.service',
            'slot-wifi-probe-recovery.service', 'sshd.service', 'slot-sharing.service',
            'wsdd2.service', 'systemd-resolved.service', 'systemd-timesyncd.service',
            'rocknix-memory-manager.service', 'openssl-config.service',
            'systemd-timesyncd-setup.service', 'tz-data.service',
            'systemd-update-utmp.service', 'systemd-update-utmp-runlevel.service')
UNUSED = ('nmbd.service', 'avahi-daemon.service', 'avahi-daemon.socket',
          'dbus-org.freedesktop.Avahi.service', 'seatd.service',
          'seat-management-daemon.service',
          'bluetooth.service', 'video.service', 'hdmi-hotplug.service', 'headphones.service',
          'volume-fixup.service', 'wireplumber@.service',
          'pipewire.service', 'pipewire.socket', 'pipewire-pulse.service',
          'pipewire-pulse.socket', 'wireplumber.service',
          'systemd-binfmt.service', 'proc-sys-fs-binfmt_misc.automount',
          'proc-sys-fs-binfmt_misc.mount', 'show-version.service')
# Slot uses GLES directly and does not decode video or route Bluetooth audio.
# Keep the baseline kernel and its recovery drivers; avoid autoloading these
# unused board devices during udev's coldplug pass.
UNUSED_MODULES = ('hci_uart', 'bluetooth', 'btrtl', 'hantro_vpu', 'rockchip_rga')
SESSION_UNITS = {
    'network-base.service': 'network', 'network-online.service': 'network',
    'NetworkManager.service': 'wifi', 'slot-wpa-supplicant.service': 'wifi',
    'slot-wifi-probe-recovery.service': 'wifi', 'sshd.service': 'ssh',
    'slot-sharing.service': 'sharing', 'wsdd2.service': 'sharing',
    'systemd-resolved.service': 'network', 'openssl-config.service': 'network',
    'systemd-timesyncd.service': 'time', 'systemd-timesyncd-setup.service': 'time',
}
DEFERRED_HOST_MODULES = ('ehci_platform', 'ohci_platform')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_hwdb(source, output):
    """Publish a complete database even when the previous image file is 0444."""
    if source.read_bytes()[:8] != b'KSLPHHRH':
        raise ValueError('Invalid compiled hardware database')
    fd, name = tempfile.mkstemp(prefix='.slot-hwdb-', dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def compile_hwdb(root, output, overrides=True):
    loader = root / 'usr/lib/ld-linux-aarch64.so.1'
    binary = root / 'usr/bin/systemd-hwdb'
    with tempfile.TemporaryDirectory(prefix='slot-hwdb-') as name:
        stage = Path(name)
        shutil.copytree(root / 'usr/lib/udev/hwdb.d', stage / 'usr/lib/udev/hwdb.d')
        defaults = root / 'usr/config/hwdb.d'
        if overrides:
            shutil.copytree(defaults, stage / 'etc/udev/hwdb.d')
        subprocess.run([str(loader), '--library-path', f'{root}/usr/lib:{root}/usr/lib/systemd',
                        str(binary), '--usr', '--root=' + str(stage), 'update'], check=True)
        install_hwdb(stage / 'usr/lib/udev/hwdb.bin', output)


def fixed_hwdb(root, compiler=compile_hwdb):
    """One board database; persistent custom calibration remains supported."""
    source = Path(__file__).parents[1] / 'config/60-rg353v.hwdb'
    folder = root / 'usr/lib/udev/hwdb.d'
    # This is an image assembly operation, never a live /storage rewrite.
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    shutil.copy2(source, folder / source.name)
    # Distribution remote-control defaults are unrelated to built-in RG353V
    # controls. Never remove a user's persistent /storage overrides here.
    defaults = root / 'usr/config/hwdb.d'
    (defaults / '99-osmcrf.hwdb').unlink(missing_ok=True)
    factory = root / 'usr/share/slot/hardware/hwdb.d'
    if factory.exists():
        shutil.rmtree(factory)
    shutil.copytree(defaults, factory)
    database = root / 'usr/lib/udev/hwdb.bin'
    compiler(root, database, overrides=False)
    if database.read_bytes()[:8] != b'KSLPHHRH':
        raise ValueError('Invalid RG353V hardware database')
    (root / 'usr/share/slot/hardware/hwdb-no-overrides.bin').unlink(missing_ok=True)
    return database, {p.name: digest(p) for p in sorted(defaults.glob('*.hwdb'))}



def graphics_prefetch(root):
    """Enable the optional hints only for the exact libraries measured on hardware."""
    folder = root / 'usr/share/slot/hardware'
    profile = folder / 'graphics-pages.list'
    link = root / 'usr/lib/systemd/system/sysinit.target.wants/slot-graphics-prefetch.service'
    link.unlink(missing_ok=True)
    result = {'enabled': False, 'reason': 'no-profile'}
    if profile.exists():
        meta = json.loads((folder / 'graphics-pages.json').read_text())
        if (meta.get('schema') != 1 or meta.get('page_bytes') != 4096
                or digest(profile) != meta.get('profile_sha256')):
            raise ValueError('Invalid measured graphics page profile')
        expected = {'/usr/lib/libgbm.so.1', '/usr/lib/libmali.so.1', '/usr/lib/libSDL2-2.0.so.0'}
        if set(meta['libraries']) != expected:
            raise ValueError('Unexpected graphics library set')
        seen = set()
        pins = {}
        active = None
        total = 0
        lines = profile.read_text().splitlines()
        if not lines or lines[0] != 'SLOT-PREFETCH-1 4096':
            raise ValueError('Invalid graphics profile header')
        for line in lines[1:]:
            fields = line.split()
            if len(fields) == 4 and fields[0] == 'FILE' and active is None:
                name = fields[1]
                if (name not in meta['libraries'] or name in seen
                        or not name.startswith('/usr/lib/') or '..' in Path(name).parts):
                    raise ValueError('Unexpected graphics profile library')
                info = meta['libraries'][name]
                if (int(fields[2]) != info['bytes'] or not 0 < info['bytes'] <= 256 << 20
                        or not re.fullmatch('[0-9a-f]{16}', fields[3])):
                    raise ValueError('Invalid graphics profile file pin')
                seen.add(name)
                pins[name] = int(fields[3], 16)
                active = info['bytes']
            elif len(fields) == 3 and fields[0] == 'RANGE' and active is not None:
                offset, length = map(int, fields[1:])
                if (offset < 0 or length <= 0 or offset % 4096 or length % 4096
                        or offset >= active or offset + length > ((active + 4095) // 4096) * 4096):
                    raise ValueError('Invalid graphics profile range')
                total += length
            elif fields == ['END'] and active is not None:
                active = None
            else:
                raise ValueError('Malformed graphics profile')
        if active is not None or seen != set(meta['libraries']) or len(seen) > 8 or total > 48 << 20:
            raise ValueError('Incomplete or oversized graphics profile')
        mismatch = []
        for name, info in meta['libraries'].items():
            library = root / name.lstrip('/')
            # Keep absolute symlinks inside the staged image namespace.
            for _ in range(16):
                if not library.is_symlink():
                    break
                target = Path(library.readlink())
                library = root / str(target).lstrip('/') if target.is_absolute() else library.parent / target
                library = Path(os.path.normpath(library))
                if not library.is_relative_to(root):
                    raise ValueError('Graphics library symlink escapes staged image')
            if library.is_symlink():
                raise ValueError('Graphics library symlink loop')
            if (not library.is_file() or library.stat().st_size != info['bytes']
                    or digest(library) != info['sha256']):
                mismatch.append(name)
            else:
                pin = 14695981039346656037
                with library.open('rb') as stream:
                    for byte in stream.read(4096):
                        pin = ((pin ^ byte) * 1099511628211) & ((1 << 64) - 1)
                if pin != pins[name]:
                    raise ValueError('Graphics header pin does not match measured library')
        result = {'enabled': not mismatch, 'reason': 'matched' if not mismatch else 'library-mismatch',
                  'mismatched_libraries': mismatch, 'advised_bytes': total}
        if not mismatch:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to('../slot-graphics-prefetch.service')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'graphics-pages-status.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def configure(root, compiler=compile_hwdb):
    root = root.resolve()
    quirks = root / 'usr/lib/autostart/quirks'
    profiles = root / 'usr/share/slot/hardware/profile.d'
    profiles.mkdir(parents=True, exist_ok=True)
    for name, source in STATIC.items():
        text = (quirks / source).read_text()
        sections = re.findall(r'cat <<EOF >(/storage/\.config/profile\.d/[A-Za-z0-9_-]+)\n(.*?)\nEOF', text, re.S)
        matches = [body for target, body in sections if target.endswith('/' + name)]
        if len(matches) != 1 or '$' in matches[0] or '`' in matches[0]:
            raise ValueError('Review changed static hardware contract: ' + source)
        (profiles / name).write_text(matches[0] + '\n')
    expected = '/sys/devices/platform/fde60000.gpu/devfreq/fde60000.gpu'
    if expected not in (profiles / '010-governors').read_text():
        raise ValueError('Review changed fixed RG353V GPU path')
    (profiles / '090-ui_service').write_text('UI_SERVICE=""\nunset MALI_DEFAULT_DISPLAY\n')
    # Every helper sourcing the system profile uses the same fixed device; no
    # strings/sed model discovery or Wayland/PulseAudio defaults are needed.
    system_profiles = root / 'etc/profile.d'
    system_profiles.mkdir(parents=True, exist_ok=True)
    (system_profiles / '002-autostart').write_text('export QUIRK_DEVICE="Anbernic RG353V"\n')
    (system_profiles / '050-sway.conf').write_text(
        'export XDG_RUNTIME_DIR=/run/0-runtime-dir\n'
        'export SDL_VIDEODRIVER=kmsdrm\n'
        'export SDL_KMSDRM_DEVICE_INDEX=0\n'
        'export SDL_AUDIODRIVER=alsa\n')
    modprobe = root / 'usr/lib/modprobe.d'
    modprobe.mkdir(parents=True, exist_ok=True)
    (modprobe / 'slot-rg353v-unused.conf').write_text(
        '# Fixed RG353V Slot appliance; direct GLES and RK817 audio.\n' +
        ''.join('blacklist ' + name + '\n' for name in UNUSED_MODULES))
    (modprobe / 'slot-rg353v-deferred-usb.conf').write_text(
        '# Prevent coldplug autoload; explicit post-shelf modprobe still works.\n' +
        ''.join('blacklist ' + name + '\n' for name in DEFERRED_HOST_MODULES))

    libraries = []
    for libdir in ('usr/lib', 'usr/lib32'):
        for variant in ('mali', 'glesonly'):
            source = root / libdir / variant
            for item in sorted(source.rglob('*')):
                if item.is_file() and not item.is_symlink():
                    dest = root / libdir / item.relative_to(source)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.unlink(missing_ok=True)
                    shutil.copy2(item, dest)
                    libraries.append({'path': str(dest.relative_to(root)), 'sha256': digest(dest)})
        gl = root / libdir / 'libGL.so'
        if gl.parent.exists():
            gl.unlink(missing_ok=True)
            gl.symlink_to('/dev/null')
    if not any('/libEGL.so' in x['path'] for x in libraries):
        raise ValueError('Missing fixed libMali EGL implementation')
    for icd in (root / 'usr/share/vulkan/icd.d').glob('panfrost_icd.*.json'):
        icd.unlink()

    for script in ('009-bluetooth', '020-set_audio_latency', '050-audio', '055-hdmi-check'):
        (root / 'usr/lib/autostart/common' / script).unlink(missing_ok=True)
    database, defaults = fixed_hwdb(root, compiler)
    # Defaults (normally empty) are persistent overrides, not baked into the
    # board DB. Both empty and unmodified setups use the same compiled file.
    if defaults:
        compiler(root, database)
    data = {'schema': 1, 'model': 'anbernic,rg353v', 'panel': 'anbernic,rg353v-panel-v2',
            'gpu': 'mali_kbase', 'hwdb_sha256': digest(database), 'default_overrides': defaults,
            'hwdb_scope': 'rg353v-built-in-inputs',
            'fixed_libraries': libraries, 'profile_files': {p.name: digest(p) for p in profiles.iterdir()}}
    (profiles.parent / 'profile.json').write_text(json.dumps(data, indent=2) + '\n')

    graphics_prefetch(root)

    units = root / 'usr/lib/systemd/system'
    # Leave the original scripts intact for first boot, changed defaults and repair.
    for unit, mode in (('userconfig.service', 'config'), ('usercache.service', 'cache')):
        dropin = units / (unit + '.d') / '40-slot-fast-check.conf'
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text('[Service]\nExecStart=\nExecStart=/usr/bin/slot-user-setup ' + mode + '\n')
    # Preserve boot/shutdown accounting, without making the shelf wait for it.
    # A late request must pull in boot accounting, not fail its Requisite check
    # if an older persistent enable link attempted both guarded units early.
    for name, old, new in (
        ('systemd-update-utmp.service', 'Before=sysinit.target\n',
         '# Slot records boot accounting after the first shelf.\n'),
        ('systemd-update-utmp-runlevel.service', 'Requisite=systemd-update-utmp.service\n',
         'Wants=systemd-update-utmp.service\n'),
    ):
        unit = units / name
        if unit.exists():
            text = unit.read_text()
            if old not in text and new not in text:
                raise ValueError('Review changed boot accounting contract: ' + name)
            unit.write_text(text.replace(old, new))
    machine_id = units / 'machine-id.service'
    if machine_id.exists():
        text = machine_id.read_text()
        original = 'ExecStart=/usr/bin/systemd-machine-id-setup'
        managed = 'ExecStart=/usr/bin/slot-machine-id-setup'
        if original not in text and managed not in text:
            raise ValueError('Review changed machine-ID setup service')
        machine_id.write_text(text.replace(original, managed))
        ready = units / 'machine-id.service.d/50-slot-persistent.conf'
        ready.parent.mkdir(parents=True, exist_ok=True)
        ready.write_text('[Unit]\nConditionPathExists=!/run/slot-machine-id-ready\n')
    timezone = units / 'tz-data.service'
    if timezone.exists():
        text = timezone.read_text()
        ordering = ('Before=systemd-udevd.service\n', 'Before=slot-rg353v.service\n')
        deferred = '# Slot uses UTC plus its saved offset; localtime is deferred.\n'
        if not any(line in text for line in (*ordering, deferred)):
            raise ValueError('Review changed timezone ordering')
        for line in ordering:
            text = text.replace(line, '')
        if deferred not in text:
            text = text.replace('[Unit]\n', '[Unit]\n' + deferred, 1)
        timezone.write_text(text)
    # Direct-IP SMB needs neither discovery daemon. Slot owns DRM/evdev directly.
    network_base = root / 'usr/sbin/network-base-setup'
    if network_base.exists():
        text = network_base.read_text()
        network_base.write_text(text.replace('avahi-set-host-name ${HOSTNAME}\n', ''))
    smbd = units / 'smbd.service'
    if smbd.exists():
        text = smbd.read_text()
        text = re.sub(r'^(Wants|Requires|After|Before)=(.*)$',
                      lambda m: m[1] + '=' + ' '.join(
                          name for name in m[2].split()
                          if name not in ('nmbd.service', 'avahi-daemon.service')),
                      text, flags=re.M)
        smbd.write_text(text)
    daemon = root / 'usr/lib/autostart/daemons/002-samba'
    if daemon.exists():
        text = daemon.read_text()
        if 'DAEMONS=("nmbd" "smbd")' in text:
            text = text.replace('DAEMONS=("nmbd" "smbd")', 'DAEMONS=("smbd")')
        elif 'DAEMONS=("smbd")' not in text:
            raise ValueError('Review changed Samba daemon list')
        daemon.write_text(text)
    for name in ('nmbd.service', 'avahi-daemon.service', 'avahi-daemon.socket',
                 'seatd.service', 'seat-management-daemon.service'):
        shutil.rmtree(units / (name + '.d'), ignore_errors=True)
    browse_alias = root / 'usr/bin/avahi-browse-domains'
    if browse_alias.is_symlink():
        if browse_alias.readlink() != Path('avahi-browse'):
            raise ValueError('Review changed Avahi browser alias')
        browse_alias.unlink()

    for unit in DEFERRED:
        for directory in units.glob('*.wants'):
            link = directory / unit
            if link.is_symlink():
                link.unlink()
        # Old releases left enabled links in /storage. A factory condition also
        # covers those links without editing persistent state or the rollback OS.
        dropin = units / (unit + '.d') / '50-slot-background.conf'
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text('[Unit]\nConditionPathExists=/run/slot-background.ready\n')
    for unit, feature in SESSION_UNITS.items():
        dropin = units / (unit + '.d') / '60-slot-session.conf'
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text('[Unit]\nConditionPathExists=/run/slot-services/' + feature + '.on\n')
    (root / 'usr/share/slot/game-startup-v1').write_text('1\n')
    (modprobe / 'slot-rg353v-wifi-demand.conf').write_text(
        '# Load the known radio only after an explicit session grant.\n'
        'blacklist rtw88_8821cs\n')
    for unit in UNUSED:
        for directory in units.glob('*.wants'):
            link = directory / unit
            if link.is_symlink():
                link.unlink()
        # A vendor mask also covers persistent enabled links from older builds.
        target = units / unit
        target.unlink(missing_ok=True)
        target.symlink_to('/dev/null')
    for unit in ('slot-background.path', 'slot-background.timer', 'slot-speaker.path'):
        link = units / 'rocknix.target.wants' / unit
        link.parent.mkdir(parents=True, exist_ok=True)
        link.unlink(missing_ok=True)
        link.symlink_to('../' + unit)
    for folder, keep in (('devices', 'Anbernic RG353V'), ('platforms', 'RK3566')):
        for path in (quirks / folder).iterdir():
            if path.name != keep:
                if path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    configure(parser.parse_args().root)
