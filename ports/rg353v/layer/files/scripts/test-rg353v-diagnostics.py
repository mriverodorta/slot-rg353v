#!/usr/bin/env python3
"""Read-only status, bounded-command and failure-path regressions."""
import importlib.machinery
import importlib.util
import json
import sys
sys.dont_write_bytecode = True
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-diagnostics'
loader = importlib.machinery.SourceFileLoader('diagnostics', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
d = importlib.util.module_from_spec(spec)
loader.exec_module(d)

class DiagnosticsTests(unittest.TestCase):
    def test_bad_protocol_values_rejected(self):
        for value in ['x\nSECRET', 'foo/bar', 'wifi name', '', 'a'*81]:
            self.assertEqual(d.ident(value), 'Unavailable')

    def test_subprocess_output_capped_and_killed(self):
        start = time.monotonic()
        text, complete = d.command(['python3', '-c', 'import sys,time; sys.stdout.write("x"*1000000); sys.stdout.flush(); time.sleep(10)'], timeout=.3, limit=1024)
        self.assertEqual(len(text), 1024); self.assertFalse(complete)
        self.assertLess(time.monotonic()-start, 2)

    def test_hung_subprocess_deadline(self):
        start = time.monotonic()
        self.assertEqual(d.command(['python3', '-c', 'import time; time.sleep(10)'], timeout=.1), ('', False))
        self.assertLess(time.monotonic()-start, 2)

    def test_command_missing_and_nonzero(self):
        self.assertEqual(d.command(['/does/not/exist']), ('', False))
        self.assertFalse(d.command(['python3', '-c', 'raise SystemExit(1)'])[1])

    def test_missing_or_corrupt_inputs(self):
        self.assertEqual(d.data('/does/not/exist'), {})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x'; p.write_text('not json')
            self.assertEqual(d.data(p), {})
            os.mkfifo(Path(tmp)/'fifo')
            self.assertEqual(d.read(Path(tmp)/'fifo'), '')

    def test_removed_export_command_is_rejected_before_collecting(self):
        for args in (['export'],[],['status','extra']):
            with patch.object(sys,'argv',['slot-diagnostics',*args]), patch.object(d,'snapshot') as collect:
                with self.assertRaises(SystemExit) as result:d.main()
                self.assertEqual(result.exception.code,2);collect.assert_not_called()

    def test_status_only_collects_and_displays(self):
        with patch.object(sys,'argv',['slot-diagnostics','status']), patch.object(d,'snapshot',return_value={'fixture':True}) as collect, patch.object(d,'ui') as display:
            d.main();collect.assert_called_once();display.assert_called_once_with({'fixture':True})

    def test_storage_collection_is_on_demand_and_does_not_restore_export(self):
        with patch.object(sys,'argv',['slot-diagnostics','status']), patch.object(d,'snapshot',return_value={}), patch.object(d,'storage_details') as storage, patch.object(d,'ui'):
            d.main(); storage.assert_not_called()
        with patch.object(sys,'argv',['slot-diagnostics','status','--storage']), patch.object(d,'snapshot',return_value={}), patch.object(d,'storage_details',return_value={'fault_path':'/storage/save.sav'}) as storage, patch.object(d,'ui') as display:
            d.main(); storage.assert_called_once(); display.assert_called_once_with({'storage_details':{'fault_path':'/storage/save.sav'}})
    def test_storage_errors_keep_path_errno_and_only_relevant_kernel_lines(self):
        def read(path,*args):
            return {'/run/slot-storage-error':'fault_path\t/storage/save.sav\nfault_errno\t30\nfault_reason\tRead-only filesystem\nignored\tsecret', '/proc/mounts':'/dev/mmcblk1p3 /storage/slotcontent exfat ro,nodev 0 0'}.get(str(path),'')
        with patch.object(d,'read',side_effect=read),patch.object(d,'command',return_value=('[1] wifi error\n[2] exfat-fs mmcblk1p3: filesystem error',True)):
            v=d.storage_details(); self.assertEqual(v['fault_errno'],'30'); self.assertIn('read-only',v['content_mount']); self.assertIn('exfat',v['fs_error']); self.assertNotIn('wifi',v['fs_error']); self.assertNotIn('ignored',v)

if __name__ == '__main__': unittest.main()
