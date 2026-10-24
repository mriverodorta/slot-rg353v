#!/bin/sh
set -eu
SYS=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=${SLOT_ROOT:-$(dirname "$SYS")}
if [ "$(id -u)" != 0 ]; then
    echo 'Run the test session as root to control display services and access DRM/input.' >&2
    exit 2
fi
command -v systemctl >/dev/null 2>&1 || { echo 'This runner expects ROCKNIX/systemd.' >&2; exit 2; }
if pgrep -x slot >/dev/null; then
    echo 'An existing slot process is running; exit it first.' >&2
    exit 2
fi
restore_units=''
child=''
cleanup() {
    trap - EXIT INT TERM HUP
    if [ -n "$child" ]; then
        kill "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
    if [ -n "$restore_units" ]; then
        # Values are fixed unit names from the list below, not user input.
        sh "$SYS/restore-display.sh" || echo "Restore failed: $restore_units" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
for unit in emustation.service essway.service sway.service; do
    state=$(systemctl is-active "$unit" 2>/dev/null || true)
    case "$state" in
        active|activating|reloading) restore_units="$restore_units $unit" ;;
    esac
done
mkdir -p "$ROOT"
printf '%s\n' "$restore_units" > "$ROOT/.slot-display-services"
if [ -n "$restore_units" ]; then
    systemctl stop $restore_units
fi
echo 'Starting slot. Eject the game to save before Ctrl-C; the normal frontend will be restored.'
if [ -f "$ROOT/slot.log" ]; then mv -f "$ROOT/slot.log" "$ROOT/slot.log.1"; fi
SLOT_ROOT="$ROOT" sh "$SYS/launch_frontend.sh" > "$ROOT/slot.log" 2>&1 &
child=$!
echo "Log: $ROOT/slot.log"
set +e
wait "$child"
status=$?
set -e
child=''
cat "$ROOT/slot.log"
exit "$status"
