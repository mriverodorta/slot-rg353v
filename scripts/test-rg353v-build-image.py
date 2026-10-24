#!/usr/bin/env python3
"""Matching source delivery stays outside the installed SYSTEM payload."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('builder',ROOT/'scripts/build-image.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SourceAsset(unittest.TestCase):
    def test_separate_source_is_copied_and_included_in_release_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);source=p/'matching.tar.gz';source.write_bytes(b'matching source fixture')
            output=p/'release';output.mkdir();image=output/'image.img.gz';image.write_bytes(b'image fixture')
            args=SimpleNamespace(version='test',lock=ROOT/'ports/rg353v/upstreams.lock.json')
            info={'profile':'release','version':'test','private':False,'source_build':False,'source_archive':str(source)}
            m.finish_record(args,info,image)
            asset=output/'Slot-RG353V-test-source.tar.gz'
            self.assertEqual(asset.read_bytes(),source.read_bytes())
            record=json.loads((output/'build.json').read_text())
            self.assertEqual(record['source_asset']['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertIn(asset.name,(output/'SHA256SUMS').read_text())
            self.assertNotIn(str(source),json.dumps(record))
            with self.assertRaisesRegex(ValueError,'Source asset output exists'):
                m.finish_record(args,info,image)

    def test_source_loader_build_enables_the_required_probe_with_the_clock_fix(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);slot=root/'slot';rocknix=root/'rocknix'
            source=slot/'dist-rg353v/Sources/slot-source.tar.gz'
            source.parent.mkdir(parents=True);source.write_bytes(b'source fixture')
            report=rocknix/'release/build-report.json';report.parent.mkdir(parents=True)
            report.write_text(json.dumps({'artifacts':{'ROCKNIX-RK3566-fixture-Generic.img.gz':{}}}))
            lock=root/'lock.json';lock.write_text('{}')
            args=SimpleNamespace(lock=lock,version='fixture')
            workflow=SimpleNamespace(prepare=lambda lock,work:{'slot':slot,'rocknix':rocknix})
            with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'load_workflow',return_value=workflow),mock.patch.object(m,'run') as run,mock.patch.object(m.subprocess,'check_output',return_value='aarch64'):
                m.source_inputs(args,{'work':str(root/'work')})
            calls=[call for call in run.call_args_list if len(call.args)>1 and Path(call.args[1]).name=='build-rg353v-bootstage.sh']
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0].args[0],'bash')
            tool_calls=[call for call in run.call_args_list if len(call.args)>1 and Path(call.args[1]).name=='build-rg353v-installer-tools.sh']
            self.assertEqual(len(tool_calls),1)
            self.assertEqual(tool_calls[0].args[0],'bash')
            for flag in ('SLOT_BOOTSTAGE_SD_PROBE','SLOT_BOOTSTAGE_SD_CLOCK_FIX','SLOT_BOOTSTAGE_EMMC_SELECT'):
                self.assertEqual(calls[0].kwargs['env'][flag],'1')

    def test_slot_packager_never_places_source_archive_in_system(self):
        text=(ROOT/'scripts/package-rg353v.sh').read_text()
        self.assertIn('-czf dist-rg353v/Sources/slot-source.tar.gz',text)
        self.assertNotIn('-czf dist-rg353v/System/licenses/slot-source.tar.gz',text)
        self.assertIn('test ! -L dist-rg353v/System/licenses/slot-source.tar.gz',text)

if __name__=='__main__':unittest.main()
