#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_image=${1:?Usage: compose-rocknix-card.sh INPUT.img.gz OUTPUT_DIR [PRIVATE_BACKUP.img]}
output_dir=${2:?Supply output directory}
backup=${3:-}
source_image=$(python3 -c 'import pathlib,sys;print(pathlib.Path(sys.argv[1]).resolve())' "$source_image")
mkdir -p "$output_dir"
output_dir=$(cd "$output_dir" && pwd)
[[ -f $source_image ]] || { echo 'Input image missing.' >&2; exit 2; }
[[ ! -e $output_dir/ROCKNIX-Slot-RG353V.img && ! -e $output_dir/ROCKNIX-Slot-RG353V.img.gz ]] || { echo 'Output already exists; nothing overwritten.' >&2; exit 2; }
if ! docker image inspect slot-rg353v-image-tools >/dev/null 2>&1; then
    docker build -t slot-rg353v-image-tools -f ports/rg353v/image/Dockerfile ports/rg353v/image
fi
backup_args=()
if [[ -n $backup ]]; then
    backup=$(python3 -c 'import pathlib,sys;print(pathlib.Path(sys.argv[1]).resolve())' "$backup")
    [[ -f $backup ]] || exit 2
    backup_args=(-v "$backup:/backup.img:ro")
fi
docker run --rm --privileged -v "$PWD:/src:ro" -v "$source_image:/upstream.img.gz:ro" \
    -v "$output_dir:/output" "${backup_args[@]}" \
    -e OUTPUT_UID="$(id -u)" -e OUTPUT_GID="$(id -g)" slot-rg353v-image-tools \
    bash -ec '
      pigz -dc /upstream.img.gz > /output/upstream.img
      args=()
      if [ -f /backup.img ]; then args=(--backup /backup.img); fi
      python3 /src/scripts/rg353v-card-layout.py --input /output/upstream.img \
        --output /output/ROCKNIX-Slot-RG353V.img --card-bytes 63864569856 "${args[@]}"
      pigz -k /output/ROCKNIX-Slot-RG353V.img
      cd /output
      sha256sum ROCKNIX-Slot-RG353V.img.gz > ROCKNIX-Slot-RG353V.img.gz.sha256
      chown "$OUTPUT_UID:$OUTPUT_GID" ROCKNIX-Slot-RG353V.img* ROCKNIX-Slot-RG353V.layout.json
      if [ -f /backup.img ]; then chmod 600 ROCKNIX-Slot-RG353V.img ROCKNIX-Slot-RG353V.img.gz; fi
      rm upstream.img
    '
echo "Ready for validation: $output_dir/ROCKNIX-Slot-RG353V.img.gz"
