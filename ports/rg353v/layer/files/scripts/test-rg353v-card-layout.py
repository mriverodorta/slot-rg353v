#!/usr/bin/env python3
"""Run inside the privileged Linux image-tools container; uses only scratch files."""
import importlib.util
import hashlib
from pathlib import Path
import tempfile
import subprocess

spec=importlib.util.spec_from_file_location('layout',Path(__file__).with_name('rg353v-card-layout.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as temp:
 r=Path(temp);src=r/'upstream.img';dst=r/'composed.img'
 with src.open('wb') as f:f.truncate(160*m.MIB)
 m.run('sgdisk','--clear','--new=1:32768:163839','--typecode=1:0700','--new=2:163840:294911','--typecode=2:8300',src)
 marker=b'bootloader preservation probe'
 with src.open('r+b') as f:f.seek(65536);f.write(marker)
 boot=r/'boot.fat';store=r/'storage.ext4'
 for p in (boot,store):
  with p.open('wb') as f:f.truncate(64*m.MIB)
 m.run('mkfs.vfat','-F','32','-n','ROCKNIX','-i','12345678',boot)
 (r/'KERNEL').write_bytes(b'kernel probe')
 m.run('mcopy','-i',boot,r/'KERNEL','::/')
 content=r/'seed';content.mkdir();(content/'.please_resize_me').touch();(content/'preserve.txt').write_text('storage probe')
 (content/'.cache/connman').mkdir(parents=True);(content/'.cache/connman/settings').write_text('[WiFi]\nEnable=true\n')
 (content/'.ssh').mkdir();(content/'.ssh/authorized_keys').write_text('public-key-probe')
 (content/'slot-dev/Games/GB').mkdir(parents=True);(content/'slot-dev/Games/GB/Probe.gb').write_bytes(b'original homebrew probe')
 m.run('mkfs.ext4','-F','-q','-L','STORAGE','-d',content,store)
 m.sparse_copy(boot,src,16*m.MIB);m.sparse_copy(store,src,80*m.MIB)
 before=hashlib.sha256(src.read_bytes()).hexdigest()
 subprocess.run(['python3',str(Path(__file__).with_name('rg353v-card-layout.py')),'--input',str(src),'--output',str(dst),'--card-bytes','63864569856','--backup',str(src)],check=True)
 assert hashlib.sha256(src.read_bytes()).hexdigest()==before
 with dst.open('rb') as f:f.seek(65536);assert f.read(len(marker))==marker
 parts=m.partitions(dst); mount=r/'mount';mount.mkdir()
 with m.mounted(dst,*parts[1],mount):assert (mount/'KERNEL').read_bytes()==b'kernel probe'
 with m.mounted(dst,*parts[2],mount):
  assert (mount/'preserve.txt').read_text()=='storage probe'
  assert not (mount/'.please_resize_me').exists()
  assert (mount/'.ssh/authorized_keys').read_text()=='public-key-probe'
  assert (mount/'.cache/services/sshd.conf').exists()
 with m.mounted(dst,*parts[3],mount):
  assert m.run('findmnt','-n','-o','FSTYPE',mount,capture=True).strip()=='exfat'
  assert (mount/'Games/GB/Probe.gb').read_bytes()==b'original homebrew probe'
 print('Image compositor passed: GPT bounds, bootloader/files preservation, resize suppression, exFAT mount and unchanged input.')
 provision=r/'private';(provision/'storage/.ssh').mkdir(parents=True)
 (provision/'storage/.ssh/authorized_keys').write_text('private-key-provision-probe')
 (provision/'storage/.ssh/authorized_keys').chmod(0o600)
 (provision/'storage/.cache/NetworkManager').mkdir(parents=True)
 (provision/'storage/.cache/NetworkManager/NetworkManager.state').write_text('[main]\nWirelessEnabled=true\n')
 (provision/'content/Games/GB').mkdir(parents=True)
 (provision/'content/Games/GB/Snapshot.gb').write_bytes(b'current snapshot homebrew probe')
 private_image=r/'private.img'
 subprocess.run(['python3',str(Path(__file__).with_name('rg353v-card-layout.py')),'--input',str(src),'--output',str(private_image),'--card-bytes',str(32*1024**3),'--games-bytes','12000000000','--provision-dir',str(provision)],check=True)
 assert private_image.stat().st_size==32*1024**3
 private_parts=m.partitions(private_image)
 with m.mounted(private_image,*private_parts[2],mount):
  key=mount/'.ssh/authorized_keys'
  assert key.read_text()=='private-key-provision-probe' and key.stat().st_mode&0o777==0o600
  assert key.stat().st_uid==0
  assert (mount/'.cache/NetworkManager/NetworkManager.state').read_text()=='[main]\nWirelessEnabled=true\n'
 with m.mounted(private_image,*private_parts[3],mount):assert (mount/'Games/GB/Snapshot.gb').read_bytes()==b'current snapshot homebrew probe'
 assert hashlib.sha256(src.read_bytes()).hexdigest()==before
 for games in (0,-m.MIB):
  try:m.layout(32*1024**3,16*m.MIB,games)
  except ValueError:pass
  else:raise AssertionError('Invalid games size accepted')
 bad=r/'bad';bad.mkdir();(bad/'entry').symlink_to(src)
 try:m.copy_provision(bad,r/'unused',['entry'])
 except ValueError:pass
 else:raise AssertionError('Provisioning symlink accepted')
 print('Private snapshot passed: custom capacity, current games/network/SSH, key ownership/mode, symlink rejection and unchanged source.')
