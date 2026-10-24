#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
image=slot-rg353v-dev:rust-1.96.1
recipe_hash=$(python3 -c 'import hashlib;from pathlib import Path;print(hashlib.sha256(Path("ports/rg353v/Dockerfile").read_bytes()).hexdigest())')
recorded=$(docker image inspect "$image" --format '{{index .Config.Labels "rg353v.dev-source"}}' 2>/dev/null || true)
if [[ $recorded != "$recipe_hash" ]]; then
    docker build --platform linux/arm64 --label "rg353v.dev-source=$recipe_hash" \
        -t "$image" -f ports/rg353v/Dockerfile ports/rg353v
fi
extra_mounts=()
if [[ -n ${SLOT_BUILD_WORKSPACE:-} ]]; then
    [[ -d $SLOT_BUILD_WORKSPACE ]] || { echo 'Build workspace does not exist.' >&2; exit 2; }
    extra_mounts=(-v "$SLOT_BUILD_WORKSPACE:$SLOT_BUILD_WORKSPACE")
fi
# Cargo metadata must remain on Linux filesystems. macOS bind-mounted
# target trees produced reproducible E0463 dependency failures on clean builds.
# Isolate caches per prepared checkout and preserve old host caches untouched.
cache_id=$(python3 -c 'import hashlib,os;print(hashlib.sha256(os.getcwd().encode()).hexdigest()[:16])')
mkdir -p target-rg353v
# macOS's Bash 3 treats an empty array as unbound under set -u.
# Permission-failure tests must obey Unix mode bits, even as container root.
exec docker run --rm --init --cap-drop=DAC_OVERRIDE --cap-drop=DAC_READ_SEARCH --platform linux/arm64 ${extra_mounts[@]+"${extra_mounts[@]}"} \
    -v "$PWD:/src" -w /src \
    --mount "type=volume,src=slot-rg353v-cargo-target-v2-$cache_id,dst=/cargo-target,volume-nocopy" \
    --mount "type=volume,src=slot-rg353v-device-target-v2-$cache_id,dst=/cargo-rg353v-target,volume-nocopy" \
    -v "$PWD/target-rg353v:/slot-build-export" \
    -e PYTHONDONTWRITEBYTECODE=1 -e RUST_TEST_THREADS=1 -e CARGO_TARGET_DIR=/cargo-target -e RUSTUP_TOOLCHAIN=1.96.1 -e SLOT_SILENT="${SLOT_SILENT:-1}" \
    -v slot-rg353v-cargo:/usr/local/cargo/registry \
    -v slot-rg353v-cargo-git:/usr/local/cargo/git \
    "$image" "$@"
