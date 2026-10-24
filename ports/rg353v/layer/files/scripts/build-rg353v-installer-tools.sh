#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
output=${1:?Supply the private task output directory}
mkdir -p "$output"
output=$(cd "$output" && pwd)
docker run --rm -v slot-rocknix-rg353v-arm-builder:/cache:ro \
 -v slot-rg353v-installer-tools:/work -v "$PWD:/src:ro" -v "$output:/task" \
 slot-rg353v-module-tools:latest bash -ec '
 root=/cache/rocknix/build.ROCKNIX-RK3566.aarch64
 test -f "$root/build/squashfs-tools-4.7/squashfs-tools/Makefile"
 mkdir -p /work/installer-tools-src
 cp -a "$root/build/squashfs-tools-4.7/squashfs-tools/." /work/installer-tools-src/
 cd /work/installer-tools-src
 make clean >/dev/null
 make -j6 LZ4_SUPPORT=1 COMP_DEFAULT=lz4 GZIP_SUPPORT= XZ_SUPPORT= LZO_SUPPORT= ZSTD_SUPPORT= XATTR_SUPPORT= LDFLAGS=-static mksquashfs unsquashfs >/task/tools-build.log 2>&1
 cc -static -O2 -Wall -Wextra -Werror -Wno-format-truncation /src/ports/rg353v/image/slot-sd-test-guard.c -o slot-sd-test-guard
 strip mksquashfs unsquashfs slot-sd-test-guard
 for tool in mksquashfs unsquashfs slot-sd-test-guard; do
   ! readelf -l "$tool" | grep -q INTERP
   cp "$tool" /task/
 done
 '
