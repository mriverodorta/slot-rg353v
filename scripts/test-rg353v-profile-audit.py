#!/usr/bin/env python3
"""Legacy and lean reports retain different audio dependencies deliberately."""
import importlib.util
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('profiles',ROOT/'scripts/compare-rg353v-builds.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
POLICY=json.loads((ROOT/'ports/rg353v/build-profiles.json').read_text())

class ProfileAudit(unittest.TestCase):
    def report(self,lean=True):
        packages=set(POLICY['retain'])
        if lean:packages-={'pipewire','wireplumber'}
        return {'profile':'normal','packages':sorted(packages),'factory_profile':{'build_profile':'normal','userspace_profile':'rg353v-lean-v1' if lean else 'baseline'},'trial_checks':{'userspace':{'profile':'rg353v-lean-v1','package_closure':'passed','sdl_build_options':'passed'}}}
    def test_qualified_lean_audio_uses_alsa_without_removed_servers(self):
        report=self.report();self.assertIn('alsa',m.audit_profile(report,POLICY))
        report['packages'].append('pipewire')
        with self.assertRaisesRegex(ValueError,'forbidden'):m.audit_profile(report,POLICY)
    def test_legacy_still_requires_the_original_audio_stack(self):
        report=self.report(False);m.audit_profile(report,POLICY)
        report['packages'].remove('pipewire')
        with self.assertRaisesRegex(ValueError,'missing runtime'):m.audit_profile(report,POLICY)
    def test_lean_cannot_hide_missing_essential_runtime_or_validation(self):
        report=self.report();report['packages'].remove('alsa')
        with self.assertRaisesRegex(ValueError,'missing runtime'):m.audit_profile(report,POLICY)
        report=self.report();report['trial_checks']={}
        with self.assertRaisesRegex(ValueError,'not validated'):m.audit_profile(report,POLICY)
        report=self.report();report['factory_profile']['userspace_profile']='unreviewed'
        with self.assertRaisesRegex(ValueError,'Unknown userspace'):m.audit_profile(report,POLICY)
if __name__=='__main__':unittest.main()
