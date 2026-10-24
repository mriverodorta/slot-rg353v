#!/usr/bin/env bash
set -euo pipefail
# Routine regression checks validate buffered audio without speaker playback.
export SLOT_SILENT=1 PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."
python3 scripts/test-rg353v-container.py
python3 scripts/test-rg353v-bootloader-build.py
python3 scripts/test-rg353v-services.py
python3 scripts/test-rg353v-kernel-profile.py
python3 scripts/test-rg353v-userspace-profile.py
python3 scripts/test-rg353v-profile-audit.py
python3 scripts/test-rg353v-firmware-trim.py
python3 scripts/test-rg353v-image-prune.py
python3 scripts/test-rg353v-boot-boost.py
python3 scripts/test-rg353v-mac-names.py
python3 scripts/test-rg353v-usb-storage.py
python3 scripts/test-rg353v-diagnostics.py
python3 scripts/test-rg353v-wifi-probe.py
python3 scripts/test-rg353v-config-check.py
python3 scripts/test-rg353v-bootsplash.py
scripts/rg353v-container.sh python3 scripts/test-rg353v-bootsplash.py
python3 scripts/test-rg353v-boot-profiler.py
python3 scripts/test-rg353v-boot-analysis.py
python3 scripts/test-rg353v-startup.py
python3 scripts/test-rg353v-emmc.py
python3 scripts/test-rg353v-os-updates.py
python3 scripts/test-rg353v-compact.py
python3 scripts/test-rg353v-clean-image.py
python3 scripts/test-rg353v-setup.py
python3 scripts/test-rg353v-updates.py
python3 scripts/test-rg353v-ota.py
python3 scripts/test-rg353v-ota-session.py
# Sealed memfd recipes require Linux even when the build host is macOS.
scripts/rg353v-container.sh python3 scripts/test-rg353v-normal-boot.py
scripts/rg353v-container.sh cargo fmt --all -- --check
scripts/rg353v-container.sh cargo clippy --workspace --all-targets -- -D warnings
scripts/rg353v-container.sh cargo clippy --target-dir /cargo-rg353v-target -p slot --no-default-features --features rg353v --all-targets -- -D warnings
scripts/rg353v-container.sh cargo test --workspace
scripts/rg353v-container.sh cargo test --target-dir /cargo-rg353v-target -p slot --lib --test sd_scan_notice --test rg353v_governor --test rg353v_upstream_features --no-default-features --features rg353v
scripts/rg353v-container.sh sh -e -c 'sh card/test-slotlink.sh
sh card/test-led.sh
sh card/test-coresave.sh'
scripts/test-rg353v-linux.sh
scripts/test-rg353v-cores.sh
scripts/test-rg353v-tools.sh
echo 'All local RG353V checks passed (physical handheld testing remains pending).'
