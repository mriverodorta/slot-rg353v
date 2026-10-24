#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=${1:-.build-rg353v/bootloader/zero-delay}
mkdir -p "$out"
out=$(cd "$out" && pwd)
[[ $(docker info --format '{{.Architecture}}') == aarch64 ]] || { echo 'Use the existing native ARM64 builder.' >&2; exit 1; }
docker volume create slot-rg353v-fastboot-experiment >/dev/null
docker run --rm --platform linux/arm64 --user 0 \
  -v slot-rocknix-rg353v-arm-builder:/baseline:ro \
  -v slot-rg353v-fastboot-experiment:/work \
  -v "$PWD/ports/rg353v/bootloader:/recipe:ro" -v "$out:/output" \
  -e OUTPUT_UID="$(id -u)" -e OUTPUT_GID="$(id -g)" \
  slot-rocknix-builder:arm64 bash /recipe/fastboot-build.sh
