#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Source pins come from the upstream taskfile; keep one source of truth.
mgba_commit=$(awk '/^  MGBA_COMMIT:/ {print $2}' taskfile.yml)
gpsp_commit=$(awk '/^  GPSP_COMMIT:/ {print $2}' taskfile.yml)
[[ $mgba_commit =~ ^[0-9a-f]{40}$ && $gpsp_commit =~ ^[0-9a-f]{40}$ ]] || exit 2
mkdir -p vendor/rg353v
if [[ ! -f vendor/rg353v/mgba_libretro.so ]] || \
   [[ "$(cat vendor/rg353v/mgba_libretro.so.meta 2>/dev/null)" != "$(sh cores/mgba/build.sh stamp "$mgba_commit")" ]]; then
    scripts/rg353v-container.sh sh cores/mgba/build.sh build "$mgba_commit" \
        target-rg353v/mgba vendor/rg353v/mgba_libretro.so
fi
archive="vendor/rg353v/gpsp-$gpsp_commit.tar.gz"
if [[ ! -f $archive ]]; then
    curl -fL --retry 3 -o "$archive.tmp" "https://github.com/libretro/gpsp/archive/$gpsp_commit.tar.gz"
    tar -tzf "$archive.tmp" > /dev/null
    mv "$archive.tmp" "$archive"
fi
if [[ ! -f vendor/rg353v/gpsp_libretro.so ]] || \
   [[ "$(cat vendor/rg353v/gpsp_libretro.so.meta 2>/dev/null)" != "$(sh cores/gpsp/build.sh stamp "$gpsp_commit")" ]]; then
    scripts/rg353v-container.sh sh cores/gpsp/build.sh build "$gpsp_commit" "$archive" \
        target-rg353v/gpsp vendor/rg353v/gpsp_libretro.so
fi
file vendor/rg353v/*_libretro.so
