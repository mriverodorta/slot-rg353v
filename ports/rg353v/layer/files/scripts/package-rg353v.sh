#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/build-rg353v.sh
scripts/build-rg353v-cores.sh
mkdir -p dist-rg353v
scripts/rg353v-container.sh target-rg353v/device/slot --init-root dist-rg353v
cp target-rg353v/device/slot dist-rg353v/System/slot
printf 'SLOT-CORE-SEALED-1\n' > dist-rg353v/System/core-verification-v1
cp vendor/rg353v/*_libretro.so dist-rg353v/System/
cp ports/rg353v/launch.sh dist-rg353v/System/launch_frontend.sh
cp ports/rg353v/rocknix/slot-rg353v/scripts/slot-ota dist-rg353v/System/slot-ota-ui
cp ports/rg353v/rocknix/slot-rg353v/scripts/slot-update dist-rg353v/System/slot-update
cp ports/rg353v/rocknix/slot-rg353v/scripts/slot-os-update dist-rg353v/System/slot-os-update
cp ports/rg353v/rocknix/slot-rg353v/scripts/slot-sharing dist-rg353v/System/slot-sharing-ui
cp ports/rg353v/rocknix/slot-rg353v/scripts/slot-ssh dist-rg353v/System/slot-ssh-ui
cp ports/rg353v/rocknix/slot-rg353v/scripts/slot-diagnostics dist-rg353v/System/slot-diagnostics-ui
cp scripts/slot-fix-mac-names.py dist-rg353v/System/slot-fix-mac-names
cp ports/rg353v/update-contract.json dist-rg353v/System/update-contract.json
cp ports/rg353v/diagnose.sh dist-rg353v/System/
cp ports/rg353v/test-session.sh dist-rg353v/System/
cp ports/rg353v/restore-display.sh dist-rg353v/System/
cp ports/rg353v/start-session.sh dist-rg353v/System/
cp -R licenses dist-rg353v/System/
mkdir -p dist-rg353v/System/licenses/core-sources
cp vendor/rg353v/*.meta vendor/rg353v/gpsp-*.tar.gz dist-rg353v/System/licenses/core-sources/
mkdir -p dist-rg353v/System/licenses/core-sources/mgba-patches dist-rg353v/System/licenses/core-sources/gpsp-patches
cp cores/mgba/*.patch dist-rg353v/System/licenses/core-sources/mgba-patches/
cp cores/gpsp/*.patch dist-rg353v/System/licenses/core-sources/gpsp-patches/
git rev-parse HEAD > dist-rg353v/System/upstream-commit.txt
git diff --binary > dist-rg353v/System/port-changes.patch
# Include new port files too; git diff alone cannot capture untracked files.
mkdir -p dist-rg353v/Sources
git ls-files -z --cached --others --exclude-standard | \
    tar --null -T - -czf dist-rg353v/Sources/slot-source.tar.gz
# Matching source is a separate release asset, never an executable payload.
test ! -L dist-rg353v/System/licenses/slot-source.tar.gz
rm -f dist-rg353v/System/licenses/slot-source.tar.gz
cp ports/rg353v/README.md dist-rg353v/PORT.md
echo 'Bundle ready: dist-rg353v (no ROMs or BIOS included).'
