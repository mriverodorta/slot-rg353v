#!/usr/bin/env python3
"""Recovery, ownership and qualification tests; never touches real Wi-Fi."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wifi_test', ROOT/'ports/rg353v/wifi-battery-test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ID = '11111111-2222-3333-4444-555555555555'


def options(**kw):
    return SimpleNamespace(mode='shelf', workload='Unchanged shelf', smoke=kw.get('smoke', False),
                           duration=kw.get('duration', 780))


def sample():
    return {'boot_id': 'boot', 'settings': {'cart': '', 'brightness': '9'},
            'governors': {'policy0': 'ondemand'}, 'frequency_limits': {'policy0': {'min': 408000}},
            'boost': 0, 'cpu_governor_tunables': {'policy0': {'sampling_rate': 20000}},
            'gpu_policy': {'gpu': {'min_freq': 400000000}}, 'mem_sleep': '[deep]'}


def module(s=None, electrical=None):
    return SimpleNamespace(Collector=lambda: SimpleNamespace(sample=lambda: s or sample()),
                           electrical=lambda _: electrical or {'charger_online': False,
                             'status': 'Discharging', 'capacity_pct': 80},
                           safe_json=lambda _: {}, read=lambda _: None)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()/'cache'
        base.mkdir()
        self.paths = patch.multiple(m, BASE=base, ACTIVE=base/'active.json',
                                    UNITS=Path(self.tmp.name)/'units', RUN_UNITS=Path(self.tmp.name)/'run')
        self.paths.start()
        self.addCleanup(self.paths.stop)
        m.UNITS.mkdir(); m.RUN_UNITS.mkdir()
        self.job = base/'test-run'; self.job.mkdir()
        self.state = {'restored': False, 'connection_uuid': ID, 'boot_id': 'boot',
                      'settings': sample()['settings'], 'options': m.validate_options(options(smoke=True)),
                      'policies': {k:v for k,v in sample().items() if k not in ('settings', 'boot_id')}}
        m.write_json(self.job/'state.json', self.state)
        m.write_json(m.ACTIVE, {'job':str(self.job)})
        self.cmd = patch.object(m, 'command', return_value='active').start()
        self.addCleanup(patch.stopall)
        patch.object(m.signal, 'signal').start()

    def test_atomic_private_state(self):
        self.assertEqual(m.read_json(self.job/'state.json'), self.state)
        self.assertEqual((self.job/'state.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.job/'state.json.tmp').exists())

    def test_job_traversal_and_nested_paths_rejected(self):
        for p in [self.job/'nested', m.BASE/'../escape', m.BASE/'with space']:
            with self.assertRaises(ValueError): m.job_path(p)
        self.assertEqual(m.job_path(self.job), self.job)

    def test_arm_durable_boot_recovery_and_independent_timer(self):
        m.arm_recovery(self.job, 300)
        text=(m.UNITS/m.RECOVERY).read_text()
        self.assertIn('After=NetworkManager.service',text)
        self.assertIn('Restart=on-failure',text)
        self.assertIn('--job '+str(self.job),text)
        self.assertTrue((m.UNITS/'multi-user.target.wants'/m.RECOVERY).is_symlink())
        self.assertIn('OnActiveSec=300',(m.RUN_UNITS/m.DEADLINE).read_text())
        self.assertIn(['systemctl','start',m.DEADLINE],[c.args[0] for c in self.cmd.call_args_list])

    def test_recovery_restores_radio_and_original_connection(self):
        m.arm_recovery(self.job,300)
        with patch.object(m,'wifi_uuid',side_effect=[None,ID]), patch.object(m,'radio',return_value='enabled'):
            self.assertTrue(m.restore(self.job,'test'))
        calls=[c.args[0] for c in self.cmd.call_args_list]
        self.assertIn(['nmcli','radio','wifi','on'],calls)
        self.assertIn(['nmcli','--wait','25','connection','up','uuid',ID,'ifname','wlan0'],calls)
        self.assertTrue(m.read_json(self.job/'state.json')['restored'])
        self.assertFalse(m.ACTIVE.exists())
        self.assertFalse((m.UNITS/m.RECOVERY).exists())
        self.assertFalse((m.RUN_UNITS/m.DEADLINE).exists())

    def test_connected_recovery_does_not_reactivate_connection(self):
        with patch.object(m,'wifi_uuid',return_value=ID), patch.object(m,'radio',return_value='enabled'):
            m.restore(self.job,'test')
        self.assertFalse(any('connection' in c.args[0] for c in self.cmd.call_args_list))

    def test_failed_reconnection_keeps_reboot_recovery_and_retry_service(self):
        m.arm_recovery(self.job,300)
        with patch.object(m,'wifi_uuid',return_value=None),patch.object(m,'radio',return_value='enabled'):
            with self.assertRaises(RuntimeError):m.restore(self.job,'failure')
        self.assertFalse(m.read_json(self.job/'state.json')['restored'])
        self.assertTrue(m.ACTIVE.exists());self.assertTrue((m.UNITS/m.RECOVERY).exists())
        self.assertIn(['systemctl','start','--no-block',m.RECOVERY],[c.args[0] for c in self.cmd.call_args_list])
        self.assertNotIn(ID,json.dumps(m.read_json(self.job/'recovery.json')))

    def test_stale_callback_cannot_change_new_experiment(self):
        m.write_json(m.ACTIVE,{'job':str(m.BASE/'new-run')})
        with self.assertRaises(ValueError):m.restore(self.job,'stale')
        self.cmd.assert_not_called()

    def test_restored_stale_callback_is_idempotent(self):
        self.state['restored']=True;m.write_json(self.job/'state.json',self.state)
        m.write_json(m.ACTIVE,{'job':str(m.BASE/'new-run')})
        self.assertTrue(m.restore(self.job,'stale'));self.cmd.assert_not_called()
        self.assertTrue(m.ACTIVE.exists())

    def test_crash_after_restore_state_finishes_cleanup(self):
        m.arm_recovery(self.job,300)
        self.state['restored']=True;m.write_json(self.job/'state.json',self.state)
        self.assertTrue(m.restore(self.job,'retry'));self.assertFalse(m.ACTIVE.exists())

    def test_invalid_uuid_rejected_without_command(self):
        self.state['connection_uuid']='bad; private network';m.write_json(self.job/'state.json',self.state)
        with self.assertRaises(ValueError):m.restore(self.job,'test')
        self.cmd.assert_not_called()

    def test_other_recovery_unit_not_deleted(self):
        (m.UNITS/m.RECOVERY).write_text('ExecStart=restore --job /other/job --reason boot')
        with self.assertRaises(ValueError):m.disarm_recovery(self.job)
        self.assertTrue((m.UNITS/m.RECOVERY).exists());self.assertTrue(m.ACTIVE.exists())

    def test_deadline_recovery_prevents_late_radio_off(self):
        self.state['restored']=True;m.write_json(self.job/'state.json',self.state)
        with self.assertRaisesRegex(RuntimeError,'Recovery'):m.disable_wifi(self.job)
        self.cmd.assert_not_called()

    def test_radio_off_requires_current_ownership(self):
        m.write_json(m.ACTIVE,{'job':str(m.BASE/'other-run')})
        with self.assertRaisesRegex(RuntimeError,'ownership'):m.disable_wifi(self.job)
        self.cmd.assert_not_called()

    def test_worker_failure_always_restores(self):
        with patch.object(m,'profiler',return_value=module()),patch.object(m.time,'sleep'), \
             patch.object(m,'phase',side_effect=RuntimeError('sampler failed')),patch.object(m,'restore') as restore:
            with self.assertRaises(RuntimeError):m.worker(self.job)
        restore.assert_called_once_with(self.job,'worker-finally')
        self.assertEqual(m.read_json(self.job/'status.json')['phase'],'aborted')

    def test_worker_signal_always_restores(self):
        with patch.object(m,'profiler',return_value=module()),patch.object(m.time,'sleep'), \
             patch.object(m,'phase',side_effect=InterruptedError()),patch.object(m,'restore') as restore:
            with self.assertRaises(InterruptedError):m.worker(self.job)
        restore.assert_called_once()

    def test_successful_smoke_never_claims_energy_savings(self):
        fake=module();fake.compare=lambda *args,**kw:{'comparable':False}
        with patch.object(m,'profiler',return_value=fake),patch.object(m.time,'sleep'), \
             patch.object(m,'phase',return_value={}),patch.object(m,'guard'), \
             patch.object(m,'radio',return_value='disabled'),patch.object(m,'export_results'),patch.object(m,'restore') as restore:
            m.worker(self.job)
        result=m.read_json(self.job/'comparison.json')
        self.assertFalse(result['comparable']);self.assertIsNone(result['power_reduction_pct'])
        self.assertTrue(result['both_phases_completed']);restore.assert_called_once()
        self.assertIn(['nmcli','radio','wifi','off'],[c.args[0] for c in self.cmd.call_args_list])

    def test_interrupted_phase_terminates_sampler_before_return(self):
        child=Mock();child.poll.return_value=None
        with patch.object(m,'guard',side_effect=[None,InterruptedError()]), \
             patch.object(m,'radio',return_value='enabled'),patch.object(m,'wifi_uuid',return_value=ID), \
             patch.object(m.subprocess,'Popen',return_value=child),patch.object(m.time,'sleep'):
            with self.assertRaises(InterruptedError):m.phase(self.job,self.state,'wifi-on',module())
        child.terminate.assert_called_once();child.wait.assert_called_once()

    def test_early_sampler_exit_rejects_phase(self):
        child=Mock();child.poll.return_value=0;child.returncode=0
        (self.job/'wifi-on').mkdir();m.write_json(self.job/'wifi-on/summary.json',{'metadata':{'stop_reason':'low_battery'}})
        with patch.object(m,'guard'),patch.object(m,'radio',return_value='enabled'), \
             patch.object(m,'wifi_uuid',return_value=ID),patch.object(m.subprocess,'Popen',return_value=child):
            with self.assertRaisesRegex(RuntimeError,'early'):m.phase(self.job,self.state,'wifi-on',module())

    def test_start_charging_rejected_before_arming_or_radio_changes(self):
        m.ACTIVE.unlink()
        fake=module(electrical={'charger_online':True,'status':'Charging','capacity_pct':99})
        with patch.object(m,'board_check'),patch.object(m,'profiler',return_value=fake),patch.object(m,'arm_recovery') as arm:
            with self.assertRaises(ValueError):m.start(options())
        arm.assert_not_called();self.cmd.assert_not_called();self.assertFalse(m.ACTIVE.exists())

    def test_start_arms_recovery_before_detached_worker(self):
        m.ACTIVE.unlink();order=Mock()
        with patch.object(m,'board_check'),patch.object(m,'profiler',return_value=module()), \
             patch.object(m,'radio',return_value='enabled'),patch.object(m,'wifi_uuid',return_value=ID), \
             patch.object(m,'arm_recovery') as arm:
            order.attach_mock(arm,'arm');order.attach_mock(self.cmd,'command')
            m.start(options())
        self.assertEqual(order.mock_calls[0][0],'arm')
        args=self.cmd.call_args.args[0]
        self.assertEqual(args[0],'systemd-run')
        self.assertTrue(any(x.startswith('--property=ExecStopPost=') for x in args))
        self.assertTrue(any(x.startswith('--property=RuntimeMaxSec=') for x in args))

    def test_public_export_excludes_private_connection_and_command_files(self):
        m.write_json(self.job/'comparison.json',{'smoke_test':True,'comparable':False})
        m.write_json(self.job/'status.json',{'phase':'complete'})
        m.write_json(self.job/'recovery.json',{'restored':True})
        (self.job/'wifi-on.stdout').write_text('SECRET_NETWORK_NAME')
        for name in ('wifi-on','wifi-off'):
            (self.job/name).mkdir()
            m.write_json(self.job/name/'summary.json',{'warnings':[]})
        with patch.object(m,'PUBLIC',Path(self.tmp.name)/'public'):
            m.export_results(self.job)
            public=m.PUBLIC/self.job.name
            files=[q for q in public.rglob('*') if q.is_file()]
            text=''.join(q.read_text() for q in files)
            self.assertNotIn(ID,text);self.assertNotIn('SECRET',text)
            self.assertFalse((public/'state.json').exists())
            self.assertIn('does not qualify',(public/'README.md').read_text())

    def test_guard_stops_after_independent_recovery(self):
        self.state['restored']=True;m.write_json(self.job/'state.json',self.state)
        with self.assertRaisesRegex(RuntimeError,'Recovery'):m.guard(self.job,self.state,module())

    def test_guard_rejects_settings_and_policy_changes(self):
        for key in ['settings','gpu_policy','cpu_governor_tunables','governors']:
            changed=sample();changed[key]={}
            with patch.object(Path,'read_text',return_value='boot'),patch.object(m,'read_json',return_value={'restored':False}):
                with self.assertRaises(RuntimeError):m.guard(self.job,self.state,module(changed))

    def test_guard_rejects_changed_boot(self):
        with patch.object(Path,'read_text',return_value='another-boot'),patch.object(m,'read_json',return_value={'restored':False}):
            with self.assertRaisesRegex(RuntimeError,'Boot'):m.guard(self.job,self.state,module())


class PreflightTests(unittest.TestCase):
    def test_qualified_run_minimums_and_smoke_is_explicit(self):
        self.assertEqual(m.validate_options(options())['warmup'],120)
        self.assertEqual(m.validate_options(options())['min_start'],35)
        for seconds in [0,60,779,1801]:
            with self.assertRaises(ValueError):m.validate_options(options(duration=seconds))
        self.assertEqual(m.validate_options(options(smoke=True))['duration'],30)

    def test_charging_low_or_unknown_battery_rejected(self):
        for e in [{'charger_online':True,'status':'Charging','capacity_pct':99},
                  {'charger_online':False,'status':'Discharging','capacity_pct':None},
                  {'charger_online':False,'status':'Discharging','capacity_pct':34}]:
            with self.assertRaises(ValueError):m.eligible(sample(),module(electrical=e),35)

    def test_valid_unplugged_battery_accepted(self):
        self.assertEqual(m.eligible(sample(),module(),35)['capacity_pct'],80)

    def test_nmcli_exception_does_not_expose_network_names(self):
        with patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='SECRET_SSID',stderr='SECRET_PASSWORD')):
            with self.assertRaises(RuntimeError) as error:m.command(['nmcli','radio','wifi'])
        self.assertNotIn('SECRET',str(error.exception))

    def test_uuid_output_is_validated(self):
        with patch.object(m,'command',return_value=ID):self.assertEqual(m.wifi_uuid(),ID)
        with patch.object(m,'command',return_value='--'):self.assertIsNone(m.wifi_uuid())


if __name__=='__main__':unittest.main()
