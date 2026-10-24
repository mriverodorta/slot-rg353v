#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Compose the lock's official upstreams, verify Slot and stage its ROCKNIX package.
# Use --update to resolve latest versions; no checkout is modified in place.
exec python3 scripts/rg353v-workflow.py build "$@"
