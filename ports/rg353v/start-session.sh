#!/bin/sh
set -eu
SYS=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
seconds=${1:-900}
case "$seconds" in ''|*[!0-9]*) echo 'Duration must be whole seconds.' >&2; exit 2 ;; esac
[ "$seconds" -ge 30 ] && [ "$seconds" -le 3600 ] || exit 2
exec systemd-run --collect --unit=slot-dev-session \
    --property="RuntimeMaxSec=$seconds" \
    --property=KillMode=control-group --property=TimeoutStopSec=10 \
    --property=SuccessExitStatus=143 \
    --property="ExecStopPost=/bin/sh $SYS/restore-display.sh" \
    /bin/sh "$SYS/test-session.sh"
