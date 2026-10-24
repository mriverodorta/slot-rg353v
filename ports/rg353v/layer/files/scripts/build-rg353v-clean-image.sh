#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
firmware=${1:?Supply the validated Generic.img.gz}
output=${2:?Supply a fresh output directory}
loader=${3:-.build-rg353v/bootloader/emmc-select-v1/rg353v-bootstage.bin}
[[ -f $firmware && -f $loader && ! -e $output ]] || { echo 'Supply firmware, a fresh output directory and the validated eMMC/F-selector loader.' >&2; exit 2; }
if ! docker image inspect slot-rg353v-image-tools >/dev/null 2>&1; then
  docker build -t slot-rg353v-image-tools -f ports/rg353v/image/Dockerfile ports/rg353v/image
fi
mkdir -m 700 -p "$output"
firmware=$(cd "$(dirname "$firmware")" && pwd)/$(basename "$firmware")
output=$(cd "$output" && pwd)
loader=$(cd "$(dirname "$loader")" && pwd)/$(basename "$loader")
docker run --rm --privileged -v "$PWD:/src:ro" -v "$firmware:/upstream.img.gz:ro" \
  -v "$loader:/installer-loader.bin:ro" \
  -v "$output:/output" -e OUTPUT_UID="$(id -u)" -e OUTPUT_GID="$(id -g)" \
  slot-rg353v-image-tools bash -ec '
    pigz -dc /upstream.img.gz > /output/upstream.img
    python3 /src/scripts/compose-rg353v-clean.py --input /output/upstream.img --output /output/RG353V-Slot-clean.img --loader /installer-loader.bin --public
    pigz -p 4 -k /output/RG353V-Slot-clean.img
    rm /output/upstream.img
    chmod 600 /output/*
    chown -R "$OUTPUT_UID:$OUTPUT_GID" /output
  '
echo "Clean candidate (hardware validation pending): $output/RG353V-Slot-clean.img.gz"
