#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/rg353v-ssh-common.sh
rg353v_ssh_args "$@"
exec ssh "${ssh_options[@]}" "$device_host" 'systemctl stop slot-dev-session.service'
