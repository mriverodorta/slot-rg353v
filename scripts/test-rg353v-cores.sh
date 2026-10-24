#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/build-rg353v-cores.sh
exec scripts/rg353v-container.sh cargo test --locked --target-dir /cargo-rg353v-target \
    -p slot --no-default-features --features rg353v --test rg353v_cores -- --ignored --nocapture
