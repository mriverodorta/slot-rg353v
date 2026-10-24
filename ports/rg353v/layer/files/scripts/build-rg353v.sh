#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec scripts/rg353v-container.sh sh -ec '
    cargo build --locked --profile device --target-dir /cargo-rg353v-target \
        -p slot --no-default-features --features rg353v
    # Only the finished executable leaves the Linux Cargo cache. Existing
    # packagers read this host export; intermediate metadata stays in Docker.
    install -D -m 755 /cargo-rg353v-target/device/slot /slot-build-export/device/slot
'
