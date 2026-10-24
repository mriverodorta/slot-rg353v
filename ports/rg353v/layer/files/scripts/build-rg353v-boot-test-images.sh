#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
firmware=${1:?Supply the validated Generic.img.gz}
snapshot=${2:?Supply the private provisioning snapshot}
card_bytes=${3:?Supply the actual target card capacity in bytes}
output=${4:?Supply a fresh output directory}
loader=${5:-.build-rg353v/bootloader/zero-delay}
for name in "$firmware" "$snapshot" "$loader"; do [[ -e $name ]] || exit 2; done
[[ ! -e $output ]] || { echo 'Output exists; refusing to overwrite it.' >&2; exit 2; }
mkdir -m 700 -p "$output"
firmware=$(cd "$(dirname "$firmware")" && pwd)/$(basename "$firmware")
report=$(dirname "$firmware")/build-report.json
snapshot=$(cd "$snapshot" && pwd)
output=$(cd "$output" && pwd)
loader=$(cd "$loader" && pwd)
docker run --rm --privileged -v "$PWD:/src:ro" -v "$firmware:/upstream.img.gz:ro" \
 -v "$report:/firmware-report.json:ro" -v "$snapshot:/snapshot:ro" -v "$loader:/loader:ro" -v "$output:/output" \
 -e CARD_BYTES="$card_bytes" -e OUTPUT_UID="$(id -u)" -e OUTPUT_GID="$(id -g)" slot-rg353v-image-tools bash -ec '
 pigz -dc /upstream.img.gz > /output/upstream.img
 python3 /src/scripts/rg353v-card-layout.py --input /output/upstream.img --output /output/RG353V-Slot-bootdelay2-control.img --card-bytes "$CARD_BYTES" --provision-dir /snapshot
 python3 /src/scripts/verify-rg353v-boot-test-image.py --image /output/RG353V-Slot-bootdelay2-control.img --snapshot /snapshot --report /output/control-validation.json --firmware-report /firmware-report.json
 python3 - <<'"'"'PY'"'"'
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,"/src/scripts")
import importlib.util
spec=importlib.util.spec_from_file_location("layout","/src/scripts/rg353v-card-layout.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path("/output");control=root/"RG353V-Slot-bootdelay2-control.img";fast=root/"RG353V-Slot-bootdelay0-test.img"
meta=json.loads(Path("/loader/manifest.json").read_text());blob=Path("/loader/rg353v-bootdelay0.bin").read_bytes();offset=meta["sd_offset_bytes"];end=offset+len(blob)
assert offset==32768 and len(blob)==meta["bytes"] and hashlib.sha256(blob).hexdigest()==meta["candidate_sha256"]
parts=m.partitions(control);assert end<parts[1][0]
with control.open("rb") as src:
 src.seek(offset);assert hashlib.sha256(src.read(len(blob))).hexdigest()==meta["baseline_sha256"]
with fast.open("xb") as dst:dst.truncate(control.stat().st_size)
m.sparse_copy(control,fast)
with fast.open("r+b") as dst:dst.seek(offset);dst.write(blob);dst.flush();__import__("os").fsync(dst.fileno())
hashes=[hashlib.sha256(),hashlib.sha256()];changed=False;pos=0
with control.open("rb") as a,fast.open("rb") as b:
 while True:
  x=a.read(8*1024**2);y=b.read(len(x))
  if not x:assert b.read(1)==b"";break
  assert len(x)==len(y)
  hashes[0].update(x);hashes[1].update(y)
  if x!=y:
   changed=True
   lo=max(0,offset-pos);hi=min(len(x),end-pos)
   assert lo<hi and x[:lo]==y[:lo] and x[hi:]==y[hi:],"Change outside bootloader region"
  pos+=len(x)
assert changed
result={"schema":1,"private":True,"card_bytes":control.stat().st_size,"only_bootloader_region_differs":True,"bootloader":meta,"firmware_profile":json.loads(Path("/firmware-report.json").read_text())["factory_profile"],"snapshot_manifest_sha256":hashlib.sha256(Path("/snapshot/snapshot.json").read_bytes()).hexdigest(),"recipe_sha256":{name:hashlib.sha256(Path("/src/scripts",name).read_bytes()).hexdigest() for name in ["rg353v-card-layout.py","verify-rg353v-boot-test-image.py"]},"images":{p.name:{"sha256":h.hexdigest(),"bytes":p.stat().st_size} for p,h in zip([control,fast],hashes)}}
(root/"test-images.json").write_text(json.dumps(result,indent=2)+"\n")
print("Both full images verified; only the bootloader region differs.")
PY
 cd /output
 pigz -p 4 -k RG353V-Slot-bootdelay2-control.img
 pigz -p 4 -k RG353V-Slot-bootdelay0-test.img
 sha256sum *.img.gz > SHA256SUMS
 chmod 600 *.img *.img.gz *.json SHA256SUMS
 chown -R "$OUTPUT_UID:$OUTPUT_GID" /output
 rm upstream.img
 '
echo "Private baseline/test images ready in: $output"
