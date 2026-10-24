#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/rg353v-container.sh python3 scripts/test-rg353v-hardware-fast.py
scripts/rg353v-container.sh python3 scripts/test-rg353v-hardware-marks.py
scripts/rg353v-container.sh cargo clippy --locked --target-dir /cargo-rg353v-target \
    -p slot --no-default-features --features rg353v -- -D warnings
scripts/rg353v-container.sh cargo test --locked --target-dir /cargo-rg353v-target \
    -p slot --no-default-features --features rg353v --lib --test rg353v --test evdev --test content --test sd_scan_notice --test label_cache --test quick_menu --test cartridge_titles
# Xvfb + Mesa exercises the real SDL/EGL/GLES path without a physical display.
# It cannot validate DRM ownership, Panfrost, panel orientation, or device input.
scripts/rg353v-container.sh timeout 90 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot-gfx \
    --no-default-features --features sdl --example sdl_smoke
scripts/rg353v-container.sh timeout 20 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 sh scripts/test-sdl-termination.sh

scripts/rg353v-container.sh timeout 60 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot-gfx \
    --no-default-features --features sdl --example boot_splash_smoke

scripts/rg353v-container.sh timeout 60 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot \
    --no-default-features --features rg353v --example content_smoke

scripts/rg353v-container.sh timeout 90 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot \
    --no-default-features --features rg353v --example cartridge_title_smoke

scripts/rg353v-container.sh timeout 60 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot \
    --no-default-features --features rg353v --example diagnostics_smoke

scripts/rg353v-container.sh timeout 30 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 SLOT_SILENT=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot \
    --no-default-features --features rg353v --example usb_storage_smoke

scripts/rg353v-container.sh timeout 60 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 SLOT_SILENT=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot-gfx \
    --no-default-features --features sdl --example rg353v_filters

scripts/rg353v-container.sh timeout 60 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 SLOT_SILENT=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot \
    --no-default-features --features rg353v --example integer_border_smoke


scripts/rg353v-container.sh timeout 60 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 SLOT_SILENT=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot \
    --no-default-features --features rg353v --example perfect_overlay_smoke

scripts/rg353v-container.sh timeout 60 xvfb-run -a -s '-screen 0 640x480x24' \
    env SDL_VIDEODRIVER=x11 LIBGL_ALWAYS_SOFTWARE=1 SLOT_SILENT=1 \
    cargo run --locked --target-dir /cargo-rg353v-target -p slot-gfx \
    --no-default-features --features sdl --example bezel_lazy_smoke
