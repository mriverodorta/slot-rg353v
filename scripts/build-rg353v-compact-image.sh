#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
firmware=${1:?Supply the validated Generic.img.gz}
snapshot=${2:?Supply a private provisioning directory}
output=${3:?Supply a fresh output directory}
[[ -f $firmware && -d $snapshot/storage && -d $snapshot/content && ! -e $output ]] || exit 2
mkdir -m 700 -p "$output"
firmware=$(cd "$(dirname "$firmware")" && pwd)/$(basename "$firmware")
snapshot=$(cd "$snapshot" && pwd)
output=$(cd "$output" && pwd)
docker run --rm --privileged -v "$PWD:/src:ro" -v "$firmware:/upstream.img.gz:ro" \
 -v "$snapshot:/snapshot:ro" -v "$output:/output" \
 -e OUTPUT_UID="$(id -u)" -e OUTPUT_GID="$(id -g)" slot-rg353v-image-tools bash -ec '
 pigz -dc /upstream.img.gz > /output/upstream.img
 python3 /src/scripts/compose-rg353v-compact.py --input /output/upstream.img --output /output/RG353V-Slot-compact-control.img --provision-dir /snapshot
 pigz -p 4 -k /output/RG353V-Slot-compact-control.img
 rm /output/upstream.img
 chmod 600 /output/*
 chown -R "$OUTPUT_UID:$OUTPUT_GID" /output
 '
echo "Compact Etcher image ready: $output/RG353V-Slot-compact-control.img.gz"
