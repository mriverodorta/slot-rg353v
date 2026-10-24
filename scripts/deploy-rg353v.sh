#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/rg353v-ssh-common.sh
rg353v_ssh_args "$@"
[[ -f dist-rg353v/System/slot ]] || { echo 'Run scripts/package-rg353v.sh first.' >&2; exit 2; }
# Only deploy System. Games, Config, Saves and States stay on the device.
# Refuse to overwrite a running executable/core. This never stops services or reboots.
tar -C dist-rg353v -cf - System | ssh "${ssh_options[@]}" "$device_host" \
    "set -eu; if pgrep -x slot >/dev/null; then echo 'Exit slot before deploying.' >&2; exit 1; fi; mkdir -p '$device_root'; tar -xf - -C '$device_root'"
echo "Deployed System to $device_host:$device_root"
