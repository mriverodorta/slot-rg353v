#!/bin/sh
set -eu
# Launch manually after stopping the existing frontend. No boot/firmware changes.
SYS=${SLOT_CORE_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
export SLOT_ROOT="${SLOT_ROOT:-$(dirname "$SYS")}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
export SDL_KMSDRM_REQUIRE_DRM_MASTER=1
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/0-runtime-dir}"
export SLOT_TRACE_INPUT="${SLOT_TRACE_INPUT:-1}"
export SLOT_TRACE_LATENCY="${SLOT_TRACE_LATENCY:-1}"
[ -d "$SLOT_ROOT" ] || mkdir -p "$SLOT_ROOT"
cd "$SLOT_ROOT"
# Use the system loader and its Mesa/ALSA/SDL2 libraries. Do not copy H700 libMali.
exec "$SYS/slot" "$@"
