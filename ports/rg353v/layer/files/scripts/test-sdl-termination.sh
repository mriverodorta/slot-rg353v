#!/bin/sh
set -eu
log=$(mktemp)
pid=''
cleanup() {
    if [ -n "$pid" ]; then kill -KILL "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
    rm -f "$log"
}
trap cleanup EXIT
/cargo-rg353v-target/debug/examples/sdl_smoke --wait-for-termination > "$log" 2>&1 &
pid=$!
tries=100
until grep -q 'SDL2 smoke passed' "$log"; do
    if ! kill -0 "$pid" 2>/dev/null || [ "$tries" -eq 0 ]; then
        cat "$log"; echo 'SDL context did not become ready.' >&2; exit 1
    fi
    tries=$((tries - 1))
    sleep 0.1
done
kill -TERM "$pid"
set +e
wait "$pid"
status=$?
set -e
pid=''
[ "$status" -eq 143 ] || { cat "$log"; echo "Unexpected termination status: $status" >&2; exit 1; }
echo 'SDL SIGTERM regression passed: the process exits rather than discarding a quit event.'
