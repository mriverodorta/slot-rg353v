#!/usr/bin/env python3
"""Fixed hardware composition, override caching and deferred access regressions."""
import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'ports/rg353v/rocknix/slot-startup-profile'


def module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


compose = module('startup_compose', PKG / 'tools/configure-startup.py')
hwdb = module('startup_hwdb', PKG / 'scripts/slot-hwdb-cache')


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_read_only_database_is_atomically_replaced_and_repeatable(self):
        source=self.root/'compiled';source.write_bytes(b'KSLPHHRHnew');source.chmod(0o444)
        output=self.root/'hwdb.bin';output.write_bytes(b'KSLPHHRHold');output.chmod(0o444)
        compose.install_hwdb(source,output)
        self.assertEqual(output.read_bytes(),b'KSLPHHRHnew')
        self.assertEqual(output.stat().st_mode & 0o777,0o444)
        compose.install_hwdb(source,output)
        self.assertEqual(list(self.root.glob('.slot-hwdb-*')),[])

    def test_failed_database_copy_retains_previous_complete_database(self):
        source=self.root/'compiled';source.write_bytes(b'KSLPHHRHnew')
        output=self.root/'hwdb.bin';output.write_bytes(b'KSLPHHRHold');output.chmod(0o444)
        with mock.patch.object(compose.shutil,'copy2',side_effect=OSError('copy interrupted')):
            with self.assertRaises(OSError):compose.install_hwdb(source,output)
        self.assertEqual(output.read_bytes(),b'KSLPHHRHold')
        self.assertEqual(list(self.root.glob('.slot-hwdb-*')),[])
        source.write_bytes(b'invalid database')
        with self.assertRaises(ValueError):compose.install_hwdb(source,output)
        self.assertEqual(output.read_bytes(),b'KSLPHHRHold')

    def fixture(self):
        (self.root / 'usr/lib/udev/hwdb.d').mkdir(parents=True)
        audio = self.root / 'usr/lib/autostart/common/050-audio'
        audio.parent.mkdir(parents=True)
        audio.write_text('if [ -n "/usr/sbin/quantum" ]; then\n /usr/sbin/quantum\nfi\n')
        for name, path in compose.STATIC.items():
            source = self.root / 'usr/lib/autostart/quirks' / path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('cat <<EOF >/storage/.config/profile.d/' + name + '\nKNOWN="yes"\n' + ('GPU_FREQ=("/sys/devices/platform/fde60000.gpu/devfreq/fde60000.gpu")\n' if name == '010-governors' else '') + 'EOF\ntrue\n')
        for directory in ('devices/Other Device', 'platforms/Other SoC'):
            (self.root / 'usr/lib/autostart/quirks' / directory).mkdir(parents=True)
        for name, content in [('usr/lib/mali/libEGL.so', b'known EGL'),
                              ('usr/lib/glesonly/libSDL2.so', b'known SDL'),
                              ('usr/config/hwdb.d/99-device.hwdb', b'factory override')]:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        # The old destination may be a symlink: replacing it must not write
        # through and corrupt the original Mesa implementation.
        (self.root / 'usr/lib/mesa-original').write_bytes(b'mesa')
        (self.root / 'usr/lib/libEGL.so').symlink_to('mesa-original')
        units = self.root / 'usr/lib/systemd/system'
        (units / 'tz-data.service').parent.mkdir(parents=True, exist_ok=True)
        (units / 'tz-data.service').write_text('[Unit]\nBefore=systemd-udevd.service\n')
        (units / 'systemd-update-utmp.service').write_text(
            '[Unit]\nBefore=sysinit.target\nBefore=shutdown.target\n'
            '[Service]\nExecStop=/usr/lib/systemd/systemd-update-utmp shutdown\n')
        (units / 'systemd-update-utmp-runlevel.service').write_text(
            '[Unit]\nRequisite=systemd-update-utmp.service\nAfter=systemd-update-utmp.service\n')
        (units / 'machine-id.service').write_text(
            '[Unit]\nBefore=systemd-journald.service\n[Service]\n'
            'ExecStart=/usr/bin/systemd-machine-id-setup\n')
        for name in compose.DEFERRED:
            link = units / 'multi-user.target.wants' / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to('../' + name)

    def configure(self):
        compose.configure(self.root, lambda _, output, overrides=True: output.write_bytes(
            b'KSLPHHRH' + (b'defaults' if overrides else b'no-overrides')))

    def test_image_has_exact_libraries_static_profiles_and_no_other_quirks(self):
        self.fixture()
        self.configure()
        self.assertEqual((self.root / 'usr/lib/libEGL.so').read_bytes(), b'known EGL')
        self.assertEqual((self.root / 'usr/lib/mesa-original').read_bytes(), b'mesa')
        self.assertFalse((self.root / 'usr/lib/autostart/quirks/devices/Other Device').exists())
        self.assertTrue((self.root / 'usr/lib/autostart/quirks/devices/Anbernic RG353V').is_dir())
        profile = json.loads((self.root / 'usr/share/slot/hardware/profile.json').read_text())
        self.assertEqual(profile['gpu'], 'mali_kbase')
        self.assertFalse((self.root / 'usr/share/slot/hardware/hwdb-no-overrides.bin').exists())
        self.assertEqual(list((self.root / 'usr/lib/udev/hwdb.d').iterdir()),
                         [self.root / 'usr/lib/udev/hwdb.d/60-rg353v.hwdb'])
        self.assertEqual(profile['hwdb_scope'], 'rg353v-built-in-inputs')
        self.assertEqual(len(profile['profile_files']), len(compose.STATIC) + 1)
        self.assertEqual((self.root / 'etc/profile.d/002-autostart').read_text(),
                         'export QUIRK_DEVICE="Anbernic RG353V"\n')
        self.assertIn('SDL_KMSDRM_DEVICE_INDEX=0',
                      (self.root / 'etc/profile.d/050-sway.conf').read_text())

    def test_netbios_discovery_is_masked_and_smbd_stays_independent(self):
        self.fixture()
        units = self.root / 'usr/lib/systemd/system'
        (units/'smbd.service').write_text('[Unit]\nWants=network-online.target nmbd.service avahi-daemon.service\nAfter=network-online.target nmbd.service avahi-daemon.service\n[Service]\nExecStart=/usr/sbin/smbd\n')
        (units/'nmbd.service.d').mkdir()
        (units/'nmbd.service.d/50-slot-background.conf').write_text('old defer guard')
        daemons = self.root/'usr/lib/autostart/daemons';daemons.mkdir(parents=True)
        (daemons/'002-samba').write_text('DAEMONS=("nmbd" "smbd")\n')
        self.configure()
        self.assertEqual((units/'nmbd.service').readlink(), Path('/dev/null'))
        self.assertFalse((units/'nmbd.service.d').exists())
        self.assertNotIn('nmbd.service', (units/'smbd.service').read_text())
        self.assertNotIn('avahi-daemon.service', (units/'smbd.service').read_text())
        self.assertIn('ExecStart=/usr/sbin/smbd', (units/'smbd.service').read_text())
        self.assertEqual((daemons/'002-samba').read_text(), 'DAEMONS=("smbd")\n')
        self.configure()
        self.assertEqual((daemons/'002-samba').read_text(), 'DAEMONS=("smbd")\n')

    def test_discovery_and_seat_daemons_cannot_be_reactivated_by_old_aliases(self):
        self.fixture()
        units = self.root / 'usr/lib/systemd/system'
        names = ('avahi-daemon.service', 'avahi-daemon.socket',
                 'dbus-org.freedesktop.Avahi.service', 'seatd.service',
                 'seat-management-daemon.service')
        for name in names:
            unit = units / name
            if 'daemon.service' in name and name != 'avahi-daemon.service':
                unit.symlink_to('seatd.service')
            else:
                unit.write_text('[Service]\nExecStart=/unused\n')
            link = units / 'graphical.target.wants' / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to('../' + name)
            dropin = units / (name + '.d')
            dropin.mkdir()
            (dropin / '50-slot-background.conf').write_text('old guard')
        self.configure()
        self.configure()
        for name in names:
            self.assertEqual((units / name).readlink(), Path('/dev/null'))
            self.assertFalse((units / 'graphical.target.wants' / name).is_symlink())
        for name in ('avahi-daemon.service', 'avahi-daemon.socket', 'seatd.service',
                     'seat-management-daemon.service'):
            self.assertFalse((units / (name + '.d')).exists())
        self.assertTrue(set(names).isdisjoint(compose.DEFERRED))

    def test_persistent_enabled_links_cannot_bypass_defer_guard(self):
        self.fixture()
        self.configure()
        units = self.root / 'usr/lib/systemd/system'
        for name in compose.DEFERRED:
            self.assertFalse((units / 'multi-user.target.wants' / name).is_symlink())
            self.assertIn('ConditionPathExists=/run/slot-background.ready',
                          (units / (name + '.d/50-slot-background.conf')).read_text())
        self.assertNotIn('Before=slot-rg353v.service', (units / 'tz-data.service').read_text())
        self.assertIn('ExecStart=/usr/bin/slot-machine-id-setup',
                      (units / 'machine-id.service').read_text())
        self.assertIn('ConditionPathExists=!/run/slot-machine-id-ready',
                      (units / 'machine-id.service.d/50-slot-persistent.conf').read_text())
        self.assertNotIn('Before=systemd-udevd.service', (units / 'tz-data.service').read_text())
        for name in ('slot-background.path', 'slot-background.timer', 'slot-speaker.path'):
            self.assertTrue((units / 'rocknix.target.wants' / name).is_symlink())
        for name in compose.UNUSED:
            self.assertEqual((units / name).readlink(), Path('/dev/null'))

    def test_only_unused_bluetooth_video_and_rga_modules_are_blacklisted(self):
        self.fixture()
        self.configure()
        text = (self.root / 'usr/lib/modprobe.d/slot-rg353v-unused.conf').read_text()
        names = {line.split()[1] for line in text.splitlines() if line.startswith('blacklist ')}
        self.assertEqual(names, {'hci_uart', 'bluetooth', 'btrtl', 'hantro_vpu', 'rockchip_rga'})
        self.assertTrue(names.isdisjoint({'mali_kbase', 'rtw88_8821cs', 'snd_soc_rk817',
                                          'rocknix_singleadc_joypad', 'dwc2', 'dwc3'}))

    def test_composition_can_be_repeated_without_restoring_generic_ordering(self):
        self.fixture()
        self.configure()
        self.configure()
        unit = self.root / 'usr/lib/systemd/system/tz-data.service'
        self.assertNotIn('Before=slot-rg353v.service', unit.read_text())
        self.assertNotIn('Before=systemd-udevd.service', unit.read_text())

    def test_network_extras_require_explicit_session_grants(self):
        self.fixture()
        self.configure()
        units = self.root / 'usr/lib/systemd/system'
        for name, feature in compose.SESSION_UNITS.items():
            self.assertIn('ConditionPathExists=/run/slot-services/' + feature + '.on',
                          (units / (name + '.d/60-slot-session.conf')).read_text())
        script = (PKG / 'scripts/slot-background-start').read_text()
        self.assertNotIn('systemctl start NetworkManager', script)
        self.assertNotIn('099-networkservices', script)
        self.assertNotIn('080-network', script)
        self.assertNotIn('081-usbgadget', script)
        self.assertNotIn('007-rootpw', script)
        self.assertIn('slot-services developer on', script)
        self.assertIn('cat /storage/.config/slot/developer-mode', script)
        self.assertEqual((self.root / 'usr/lib/modprobe.d/slot-rg353v-wifi-demand.conf').read_text().splitlines()[-1],
                         'blacklist rtw88_8821cs')

    def test_accounting_keeps_shutdown_hook_and_orders_late_boot_before_runlevel(self):
        self.fixture()
        self.configure()
        units = self.root / 'usr/lib/systemd/system'
        boot = (units / 'systemd-update-utmp.service').read_text()
        level = (units / 'systemd-update-utmp-runlevel.service').read_text()
        self.assertNotIn('Before=sysinit.target', boot)
        self.assertIn('Before=shutdown.target', boot)
        self.assertIn('systemd-update-utmp shutdown', boot)
        self.assertIn('Wants=systemd-update-utmp.service', level)
        self.assertIn('After=systemd-update-utmp.service', level)
        self.assertNotIn('Requisite=', level)
        script = (PKG / 'scripts/slot-background-start').read_text()
        self.assertLess(script.index('touch /run/slot-background.ready'),
                        script.index('systemctl start --no-block systemd-update-utmp-runlevel.service'))

    def test_changed_upstream_static_contract_stops_composition(self):
        self.fixture()
        source = self.root / 'usr/lib/autostart/quirks' / next(iter(compose.STATIC.values()))
        source.write_text(source.read_text().replace('KNOWN="yes"', 'KNOWN="$runtime_probe"'))
        with self.assertRaisesRegex(ValueError, 'Review changed static hardware contract'):
            self.configure()

    def cache_fixture(self):
        overrides = self.root / 'overrides'
        overrides.mkdir()
        factory = self.root / 'profile.json'
        factory.write_text(json.dumps({'default_overrides': {}, 'hwdb_sha256': 'vendor-database'}))
        runtime = self.root / 'run.bin'
        calls = []
        def compile_db(out):
            calls.append(True)
            out.write_bytes(b'KSLPHHRH' + str(len(calls)).encode())
        def prepare():
            return hwdb.prepare(factory, overrides, self.root / 'cache', runtime, compile_db)
        return overrides, factory, runtime, calls, prepare

    def test_factory_requires_no_compile_and_clears_stale_runtime_database(self):
        _, _, runtime, calls, prepare = self.cache_fixture()
        runtime.symlink_to(self.root / 'previous-database')
        self.assertEqual(prepare(), 'factory')
        self.assertEqual(calls, [])
        self.assertFalse(runtime.is_symlink())

    def test_override_changes_compile_once_and_reuse_cache(self):
        overrides, _, runtime, calls, prepare = self.cache_fixture()
        custom = overrides / '10-custom.hwdb'
        custom.write_text('custom')
        self.assertEqual(prepare(), 'cache')
        self.assertTrue(runtime.is_symlink())
        prepare()
        self.assertEqual(len(calls), 1)
        custom.write_text('changed')
        prepare()
        self.assertEqual(len(calls), 2)
        custom.unlink()
        self.assertEqual(prepare(), 'factory')
        self.assertFalse(runtime.exists())

    def test_corrupt_cache_and_changed_vendor_database_rebuild(self):
        overrides, factory, runtime, calls, prepare = self.cache_fixture()
        (overrides / '10-custom.hwdb').write_text('custom')
        prepare()
        runtime.write_bytes(b'corrupt')
        prepare()
        self.assertEqual(len(calls), 2)
        profile = json.loads(factory.read_text())
        profile['hwdb_sha256'] = 'new-vendor-database'
        factory.write_text(json.dumps(profile))
        prepare()
        self.assertEqual(len(calls), 3)

    def test_devnull_mask_is_a_real_override(self):
        overrides, _, _, calls, prepare = self.cache_fixture()
        (overrides / '20-vendor.hwdb').symlink_to('/dev/null')
        self.assertEqual(prepare(), 'cache')
        self.assertEqual(len(calls), 1)

    def test_background_has_display_trigger_and_bounded_fallback(self):
        text = (PKG / 'system.d/slot-background.path').read_text()
        self.assertIn('PathExists=/run/slot-boot/frontend/first-frame', text)
        timer = (PKG / 'system.d/slot-background.timer').read_text()
        self.assertIn('OnBootSec=20s', timer)
        self.assertIn('Unit=slot-background.service', timer)
        script = (PKG / 'scripts/slot-background-start').read_text()
        self.assertIn('touch /run/slot-background.ready', script)
        self.assertIn('slot-services developer on', script)

    def test_hardware_environment_reaches_child_setup_scripts(self):
        profile = self.root / 'profile'
        profile.write_text('ALSA_PRIMARY_CARD=1\nDEVICE_PWM_MOTOR=pwmchip1\n')
        for script, end in [('slot-hardware-start', 'model='), ('slot-background-start', 'log=')]:
            prefix = (PKG / 'scripts' / script).read_text().split(end, 1)[0]
            if script == 'slot-background-start':
                prefix = 'set -a\n. /etc/profile\n'
            prefix = prefix.replace('. /etc/profile.d/001-functions', '. /etc/profile')
            prefix = prefix.replace('. /etc/profile', '. "' + str(profile) + '"')
            subprocess.run(['bash', '-c', prefix + "\nbash -c 'test \"$ALSA_PRIMARY_CARD\" = 1 && test \"$DEVICE_PWM_MOTOR\" = pwmchip1'"], check=True)

    def test_factory_shell_path_avoids_python_but_custom_changes_use_it(self):
        factory, custom = self.root / 'factory', self.root / 'custom'
        factory.mkdir(); custom.mkdir()
        for folder in (factory, custom):
            (folder / '99-device.hwdb').write_text('factory rules')
        vendor, runtime = self.root / 'vendor.bin', self.root / 'run.bin'
        vendor.write_bytes(b'KSLPHHRHdatabase')
        runtime.write_bytes(b'stale')
        script = (PKG / 'scripts/slot-hwdb').read_text()
        for source, dest in [('/usr/share/slot/hardware/hwdb.d', factory),
                             ('/etc/udev/hwdb.d', custom), ('/usr/lib/udev/hwdb.bin', vendor),
                             ('/run/hwdb.bin', runtime)]:
            script = script.replace(source, str(dest))
        script = script.replace('exec /usr/bin/python3 /usr/lib/slot/hwdb-cache', 'exit 42')
        def run(): return subprocess.run(['sh', '-c', script], capture_output=True).returncode
        self.assertEqual(run(), 0)
        self.assertFalse(runtime.exists())
        (custom / '99-device.hwdb').write_text('modified')
        self.assertEqual(run(), 42)
        (custom / '99-device.hwdb').write_text('factory rules')
        (custom / '10-custom.hwdb').symlink_to('/dev/null')
        self.assertEqual(run(), 42)
        (custom / '10-custom.hwdb').unlink()
        (custom / '99-device.hwdb').unlink()
        self.assertEqual(run(), 0)
        self.assertFalse(runtime.exists())
        # A mask in an otherwise empty directory must use the custom path.
        (custom / '20-mask.hwdb').symlink_to('/dev/null')
        self.assertEqual(run(), 42)

    def test_fixed_speaker_is_deferred_without_network_or_external_routing(self):
        script = (PKG / 'scripts/slot-hardware-start').read_text()
        self.assertNotIn('050-audio', script)
        self.assertNotIn('set_audio_latency', script)
        self.assertNotIn('098-deviceutils', script)
        self.assertNotIn('009-bluetooth', (PKG / 'scripts/slot-background-start').read_text())
        speaker = (PKG / 'scripts/slot-speaker-start').read_text()
        self.assertIn('exec /usr/bin/slot-audio-route', speaker)
        self.assertNotIn('pactl', speaker)
        self.assertIn('first-frame', (PKG / 'system.d/slot-speaker.path').read_text())

    def test_analog_routing_uses_real_jack_events_and_clears_readiness_on_stop(self):
        source = (PKG / 'src/slot-audio-route.c').read_text()
        self.assertIn('"Headphones Jack"', source)
        self.assertIn('"Playback Mux"', source)
        self.assertLess(source.index('snd_ctl_subscribe_events(ctl, 1)'), source.index('rc = sync_route(ctl'))
        self.assertIn('snd_ctl_read(ctl, event)', source)
        self.assertNotIn('sleep(', source)
        service = (PKG / 'system.d/slot-speaker.service').read_text()
        self.assertIn('Type=simple', service)
        self.assertIn('ExecStopPost=/bin/rm -f /run/slot-speaker.ready', service)
        self.assertIn('Restart=on-failure', service)

    def test_full_revision_audit_waits_for_a_real_frame_and_uses_idle_priority(self):
        script = (PKG / 'scripts/slot-background-start').read_text()
        self.assertIn('systemctl start --no-block slot-revision-audit.timer', script)
        timer = (PKG / 'system.d/slot-revision-audit.timer').read_text()
        self.assertIn('OnActiveSec=3s', timer)
        unit = (PKG / 'system.d/slot-revision-audit.service').read_text()
        self.assertIn('ConditionPathExists=/run/slot-boot/frontend/first-frame', unit)
        self.assertIn('ExecStart=/usr/bin/slot-update audit', unit)
        self.assertIn('Nice=19', unit)
        self.assertIn('IOSchedulingClass=idle', unit)
        # The recovery timer may start networking before a late/missing frame;
        # the audit must not be independently enabled by an early boot target.
        self.assertNotIn('[Install]', unit)
        self.assertNotIn('[Install]', timer)


if __name__ == '__main__':
    unittest.main()
