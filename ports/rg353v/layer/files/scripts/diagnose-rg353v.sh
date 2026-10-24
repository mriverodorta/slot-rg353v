#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/rg353v-ssh-common.sh
rg353v_ssh_args "$@"
mkdir -p local-logs
log="local-logs/rg353v-survey-$(date +%Y%m%d-%H%M%S).txt"
ssh "${ssh_options[@]}" "$device_host" sh -s < ports/rg353v/diagnose.sh | tee "$log"
echo "Saved $log"
