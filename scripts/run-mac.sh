#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SLOT_ROOT="${SLOT_ROOT:-$PWD/sdcard}"
export SLOT_WINDOW="${SLOT_WINDOW:-1280x960}"
export SLOT_BARE=1
export SLOT_SILENT="${SLOT_SILENT:-0}"
cargo run --locked -p slot -- --init-root "$SLOT_ROOT"
exec cargo run --locked -p slot
