#!/usr/bin/env bash
# Exercise the remote runner's recovery paths with local service/process doubles.
# No network connection or real service changes are made.
set -euo pipefail
cd "$(dirname "$0")/.."
repository=$PWD
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
mkdir -p "$temporary/bin" "$temporary/slot/System"
cp ports/rg353v/test-session.sh "$temporary/slot/System/"
cp ports/rg353v/restore-display.sh "$temporary/slot/System/"
cp ports/rg353v/launch.sh "$temporary/slot/System/launch_frontend.sh"
cat > "$temporary/bin/id" <<'EOF'
#!/bin/sh
echo 0
EOF
cat > "$temporary/bin/pgrep" <<'EOF'
#!/bin/sh
exit 1
EOF
cat > "$temporary/bin/systemctl" <<'EOF'
#!/bin/sh
if [ "$1" = is-active ]; then
    case "$2" in
        essway.service) echo active; exit 0 ;;
        sway.service) echo activating; exit 3 ;;
        *) echo inactive; exit 3 ;;
    esac
fi
printf '%s\n' "$*" >> "$SERVICE_TRACE"
EOF
cat > "$temporary/slot/System/slot" <<'EOF'
#!/bin/sh
echo 'simulated graphics initialization failure'
exit 42
EOF
chmod +x "$temporary/bin/"* "$temporary/slot/System/slot"
export SERVICE_TRACE="$temporary/services.log"
set +e
PATH="$temporary/bin:$PATH" sh "$temporary/slot/System/test-session.sh" > "$temporary/run.log" 2>&1
status=$?
set -e
[[ $status == 42 ]] || { cat "$temporary/run.log"; echo "Runner lost child exit status: $status" >&2; exit 1; }
[[ $(cat "$SERVICE_TRACE") == $'stop essway.service sway.service\nstart --no-block essway.service sway.service' ]] || \
    { cat "$SERVICE_TRACE"; echo 'Runner did not restore exactly the previously active services.' >&2; exit 1; }

# A stop failure must also run restoration rather than leaving the display down.
cat > "$temporary/bin/systemctl" <<'EOF'
#!/bin/sh
if [ "$1" = is-active ]; then echo active; exit 0; fi
printf '%s\n' "$*" >> "$SERVICE_TRACE"
if [ "$1" = stop ]; then exit 7; fi
EOF
: > "$SERVICE_TRACE"
set +e
PATH="$temporary/bin:$PATH" sh "$temporary/slot/System/test-session.sh" > "$temporary/run.log" 2>&1
status=$?
set -e
[[ $status == 7 ]] || exit 1
grep -q '^start --no-block emustation.service essway.service sway.service$' "$SERVICE_TRACE"

# Shell metacharacters and paths outside the test storage root cannot reach SSH.
for root in / /storage /storage// /storage/../boot '/storage/slot;reboot' '/storage/a b'; do
    if bash -c 'source "$1"; rg353v_ssh_args root@127.0.0.1 "$2"' \
        _ "$repository/scripts/rg353v-ssh-common.sh" "$root" >/dev/null 2>&1; then
        echo "Accepted unsafe remote root: $root" >&2
        exit 1
    fi
done
bash -c 'source "$1"; rg353v_ssh_args root@127.0.0.1 /storage/slot-dev' \
    _ "$repository/scripts/rg353v-ssh-common.sh"
echo 'RG353V tools passed: failed launches/stop recovery and SSH argument validation.'
