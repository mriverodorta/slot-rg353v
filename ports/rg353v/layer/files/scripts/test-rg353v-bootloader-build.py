#!/usr/bin/env python3
"""Boot metadata is repeatable without changing FIT payloads or weakening hashes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import sys
sys.dont_write_bytecode = True

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'ports/rg353v/rocknix/slot-startup-profile/tools/configure-bootloader.py'
spec=importlib.util.spec_from_file_location('boot_build',TOOL)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fit(timestamp=7,duplicate=False):
    structure=struct.pack('>I',1)+b'\0'*4
    structure+=struct.pack('>4I',3,4,0,timestamp)
    if duplicate: structure+=struct.pack('>4I',3,4,0,timestamp)
    structure+=struct.pack('>4I',1,0,2,2)+struct.pack('>I',9)
    strings=b'timestamp\0'
    total=56+len(structure)+len(strings)
    header=struct.pack('>10I',0xd00dfeed,total,56,56+len(structure),40,17,16,0,len(strings),len(structure))
    return header+b'\0'*16+structure+strings+b'EXTERNAL-PAYLOAD-UNCHANGED\0'


class BootBuild(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'u-boot.itb'

    def test_timestamp_preserves_layout_external_data_and_all_other_bytes(self):
        original=fit();self.path.write_bytes(original)
        m.set_fit_timestamp(self.path,1791984674);result=self.path.read_bytes()
        self.assertEqual(len(result),len(original))
        self.assertEqual(result[:76],original[:76]);self.assertEqual(result[80:],original[80:])
        self.assertEqual(struct.unpack_from('>I',result,76)[0],1791984674)
        m.set_fit_timestamp(self.path,1791984674);self.assertEqual(self.path.read_bytes(),result)

    def test_invalid_or_duplicate_metadata_does_not_write(self):
        for original in (b'not a FIT',fit(duplicate=True),fit().replace(b'timestamp',b'notastamp')):
            self.path.write_bytes(original)
            with self.assertRaises(ValueError):m.set_fit_timestamp(self.path,42)
            self.assertEqual(self.path.read_bytes(),original)
        self.path.write_bytes(fit())
        with self.assertRaises(ValueError):m.set_fit_timestamp(self.path,2**32)
        alias=self.root/'alias';alias.symlink_to(self.path)
        with self.assertRaises(ValueError):m.set_fit_timestamp(alias,42)

    def prepare(self):
        recipes={};originals={}
        for name in ('u-boot-Generic','u-boot-Specific'):
            p=self.root/'projects/ROCKNIX/devices/RK3566/packages'/name/'package.mk'
            p.parent.mkdir(parents=True)
            text='make_target() {\n  printf "%s" "$SOURCE_DATE_EPOCH" > compiler-epoch\n}\n'
            p.write_text(text);originals[p]=text
            recipes[name]={'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
                'compiler_epoch':12,'fit_epoch':14,'output_sha256':hashlib.sha256(b'qualified').hexdigest()}
        policy=self.root/'policy.json';policy.write_text(json.dumps({'schema':1,'recipes':recipes}))
        return policy,originals

    def test_staging_is_idempotent_and_rejects_changed_recipe_before_any_write(self):
        policy,originals=self.prepare();m.stage(self.root,policy)
        staged={p:p.read_text() for p in originals};m.stage(self.root,policy)
        self.assertEqual(staged,{p:p.read_text() for p in originals})
        bad=list(originals)[1];bad.write_text('unreviewed upstream')
        with self.assertRaisesRegex(ValueError,'changed upstream'):m.stage(self.root,policy)
        self.assertEqual(list(staged)[0].read_text(),list(staged.values())[0])
        self.assertEqual(bad.read_text(),'unreviewed upstream')

    def test_generated_hook_freezes_metadata_checks_identity_and_scopes_environment(self):
        policy,originals=self.prepare();m.stage(self.root,policy)
        dest=self.root/'projects/ROCKNIX/devices/RK3566/packages/slot-startup-profile/tools/configure-bootloader.py'
        dest.parent.mkdir(parents=True);shutil.copy2(TOOL,dest)
        self.path.write_bytes(fit())
        helper=self.root/'rkhelper';helper.write_text('printf qualified > uboot.bin\n')
        recipe=list(originals)[0]
        script='set -e; unset SOURCE_DATE_EPOCH; PROJECT_DIR="$1/projects"; PROJECT=ROCKNIX; PKG_BUILD="$1"; find_file_path() { FOUND_PATH="$PKG_BUILD/rkhelper"; }; source "$2"; cd "$PKG_BUILD"; make_target; test -z "${SOURCE_DATE_EPOCH:-}"'
        subprocess.run(['bash','-ec',script,'test',str(self.root),str(recipe)],check=True,capture_output=True)
        self.assertEqual((self.root/'compiler-epoch').read_text(),'12')
        self.assertEqual(struct.unpack_from('>I',self.path.read_bytes(),76)[0],14)
        helper.write_text('printf changed > uboot.bin\n')
        result=subprocess.run(['bash','-ec',script,'test',str(self.root),str(recipe)],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'loader identity differs',result.stderr)

if __name__=='__main__':unittest.main()
