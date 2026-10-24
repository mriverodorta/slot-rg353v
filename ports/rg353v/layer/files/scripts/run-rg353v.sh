#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/rg353v-ssh-common.sh
rg353v_ssh_args "$@"
# The PTY delivers Ctrl-C/HUP to the remote test shell so it can restore services.
exec ssh "${ssh_options[@]}" -tt "$device_host" "sh '$device_root/System/test-session.sh'"
