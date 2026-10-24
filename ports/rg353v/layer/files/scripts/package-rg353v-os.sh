#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
firmware=${1:?Usage: package-rg353v-os.sh FIRMWARE.tar RELEASE_ID OUTPUT_DIR}
version=${2:?Supply a unique release id}
out=${3:?Supply output directory}
firmware=$(python3 -c 'import pathlib,sys;print(pathlib.Path(sys.argv[1]).resolve())' "$firmware")
mkdir -p "$out"
out=$(cd "$out" && pwd)
if ! docker image inspect slot-rg353v-image-tools >/dev/null 2>&1; then
  docker build -t slot-rg353v-image-tools -f ports/rg353v/image/Dockerfile ports/rg353v/image
fi
docker run --rm -v "$PWD:/src:ro" -v "$firmware:/firmware.tar:ro" -v "$out:/output" \
  slot-rg353v-image-tools python3 /src/scripts/package-rg353v-os.py \
  --firmware /firmware.tar --id "$version" --output "/output/$version.tar.gz"
