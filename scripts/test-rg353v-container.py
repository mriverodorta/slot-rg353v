#!/usr/bin/env python3
"""Docker command contracts: Cargo stays on Linux; only built executables export."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
class Container(unittest.TestCase):
    def run_wrapper(self, root, *args):
        (root/'scripts').mkdir(parents=True)
        (root/'ports/rg353v').mkdir(parents=True)
        shutil.copy2(ROOT/'scripts/rg353v-container.sh', root/'scripts/rg353v-container.sh')
        (root/'ports/rg353v/Dockerfile').write_text('FROM fixture\n')
        recipe=hashlib.sha256(b'FROM fixture\n').hexdigest()
        mock=root/'bin';mock.mkdir()
        docker=mock/'docker'
        docker.write_text('#!/usr/bin/env python3\nimport os,sys,json\nfrom pathlib import Path\n'
                          f'if sys.argv[1:3]==["image","inspect"]: print({recipe!r})\n'
                          'else: Path(os.environ["DOCKER_LOG"]).write_text(json.dumps(sys.argv[1:]))\n')
        docker.chmod(0o755)
        log=root/'docker.json'
        env=dict(os.environ,PATH=str(mock)+os.pathsep+os.environ['PATH'],DOCKER_LOG=str(log))
        env.pop('SLOT_BUILD_WORKSPACE',None)
        subprocess.run(['bash',str(root/'scripts/rg353v-container.sh'),*args],check=True,env=env,capture_output=True)
        return json.loads(log.read_text())
    def test_targets_are_linux_volumes_and_exports_keep_space_in_path(self):
        with tempfile.TemporaryDirectory(prefix='slot build ') as name:
            root=Path(name)
            args=self.run_wrapper(root,'cargo','test','--workspace')
            mounts=[args[i+1] for i,v in enumerate(args[:-1]) if v=='--mount']
            self.assertEqual(len(mounts),2)
            self.assertTrue(all('type=volume' in v and 'volume-nocopy' in v for v in mounts))
            self.assertTrue(any('dst=/cargo-target,' in v for v in mounts))
            self.assertTrue(any('dst=/cargo-rg353v-target,' in v for v in mounts))
            self.assertIn(str(root)+'/target-rg353v:/slot-build-export',args)
            self.assertEqual(args[-3:],['cargo','test','--workspace'])
            self.assertIn('CARGO_TARGET_DIR=/cargo-target',args)
            self.assertIn('RUST_TEST_THREADS=1',args)
            self.assertTrue((root/'target-rg353v').is_dir())
            self.assertIn('--cap-drop=DAC_OVERRIDE',args)
            self.assertIn('--cap-drop=DAC_READ_SEARCH',args)
    def test_prepared_checkouts_have_separate_artifact_caches(self):
        with tempfile.TemporaryDirectory() as name:
            a=self.run_wrapper(Path(name)/'first','true')
            b=self.run_wrapper(Path(name)/'second','true')
            def volumes(args):return {v for v in args if v.startswith('type=volume,')}
            self.assertFalse(volumes(a)&volumes(b))
if __name__=='__main__':unittest.main()
