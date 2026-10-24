#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/rg353v-ssh-common.sh
rg353v_ssh_args "$@"
mkdir -p local-logs
output="local-logs/rg353v-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$output"
for name in slot.log input-trace.log input-latency.log ags-shutdown-trace.log; do
    if ssh "${ssh_options[@]}" "$device_host" "test -f '$device_root/$name'"; then
        scp "${ssh_options[@]}" "$device_host:$device_root/$name" "$output/$name"
    fi
done
echo "Logs saved to $output"
