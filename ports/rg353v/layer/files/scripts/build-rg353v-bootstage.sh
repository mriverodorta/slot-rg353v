#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=${1:-.build-rg353v/bootloader/bootstage}
mkdir -p "$out"
out=$(cd "$out" && pwd)
[[ $(docker info --format '{{.Architecture}}') == aarch64 ]] || { echo 'Use the existing native ARM64 builder.' >&2; exit 1; }
docker volume create slot-rg353v-bootstage-experiment >/dev/null
docker run --rm --platform linux/arm64 --user 0 \
  -v slot-rocknix-rg353v-arm-builder:/baseline:ro \
  -v slot-rg353v-bootstage-experiment:/work \
  -v "$PWD/ports/rg353v/bootloader:/recipe:ro" -v "$out:/output" \
  -v "$PWD/ports/rg353v/rocknix/slot-startup-profile/tools/configure-bootloader.py:/fit-metadata.py:ro" \
  -e OUTPUT_UID="$(id -u)" -e OUTPUT_GID="$(id -g)" \
  -e SLOT_BOOTSTAGE_SD_PROBE="${SLOT_BOOTSTAGE_SD_PROBE:-0}" \
  -e SLOT_BOOTSTAGE_SD_CLOCK_FIX="${SLOT_BOOTSTAGE_SD_CLOCK_FIX:-0}" \
  -e SLOT_BOOTSTAGE_EMMC_SELECT="${SLOT_BOOTSTAGE_EMMC_SELECT:-0}" \
  slot-rocknix-builder:arm64 bash /recipe/bootstage-build.sh
