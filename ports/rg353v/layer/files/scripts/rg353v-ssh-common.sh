#!/usr/bin/env bash
# Sourced by the SSH commands. Restrict values used in remote shell commands.
rg353v_ssh_args() {
    ssh_options=()
    if [[ -n ${SLOT_SSH_KEY:-} ]]; then
        [[ -f $SLOT_SSH_KEY ]] || { echo 'SLOT_SSH_KEY must name an existing key file.' >&2; exit 2; }
        ssh_options=(-i "$SLOT_SSH_KEY" -o IdentitiesOnly=yes)
    fi
    if [[ $# -lt 1 || $# -gt 2 ]]; then
        echo "Usage: $0 USER@HOST [/storage/slot-dev]" >&2
        exit 2
    fi
    device_host=$1
    device_root=${2:-/storage/slot-dev}
    if [[ ! $device_host =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.@:-]*$ ]]; then
        echo 'Use a hostname/IP, optionally prefixed by USER@ (no shell characters).' >&2
        exit 2
    fi
    if [[ ! $device_root =~ ^/storage/[a-zA-Z0-9_-]+(/[a-zA-Z0-9_.-]+)*$ || $device_root == *..* ]]; then
        echo 'The test directory must be below /storage with no spaces or parent traversal.' >&2
        exit 2
    fi
}
