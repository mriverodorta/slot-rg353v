#!/usr/bin/env bash
# One-time upgrade of the existing development image; no boot/content writes.
set -euo pipefail
cd "$(dirname "$0")/.."
host=${1:?Usage: bootstrap-rg353v-updater.sh root@HANDHELD_IP}
key=${SLOT_SSH_KEY:-$HOME/.ssh/slot_rg353v_ed25519}
ssh_args=(-i "$key" -o BatchMode=yes -o ConnectTimeout=5)
remote_dir=$(ssh "${ssh_args[@]}" "$host" 'mktemp -d /storage/.slot-updater-bootstrap-XXXXXX')
[[ $remote_dir == /storage/.slot-updater-bootstrap-* ]] || exit 1
base=ports/rg353v/rocknix/slot-rg353v
scp "${ssh_args[@]}" "$base/scripts/slot-update" "$base/scripts/slot-os-update" "$base/scripts/slot-ota" \
  "$base/config/update-keys/development.pem" "$base/system.d/slot-os-guard.service" \
  "$base/system.d/slot-os-health.service" "$host:$remote_dir/"
ssh "${ssh_args[@]}" "$host" sh -s -- "$remote_dir" <<'REMOTE'
set -eu
temp=$1
trap 'rm -rf "$temp"' EXIT
for name in slot-update slot-os-update slot-ota; do
  python3 -m py_compile "$temp/$name"
  chmod 755 "$temp/$name"
  mv "$temp/$name" "/storage/$name.py"
done
mkdir -p /storage/.config/slot-update-keys /storage/.config/system.d/rocknix.target.wants \
  /storage/.config/system.d/slot-rg353v.service.d
mv "$temp/development.pem" /storage/.config/slot-update-keys/development.pem
cat > "$temp/slot-dispatch" <<'EOF'
#!/bin/sh
set -eu
if [ -x /usr/bin/slot-update ] && [ -f /usr/share/slot/os-profile.json ]; then
  exec /usr/bin/slot-start
fi
exec /usr/bin/python3 /storage/slot-update.py run
EOF
cat > "$temp/slot-os-dispatch" <<'EOF'
#!/bin/sh
set -eu
if [ -x /usr/bin/slot-os-update ]; then
  exec /usr/bin/slot-os-update "$@"
fi
exec /usr/bin/python3 /storage/slot-os-update.py "$@"
EOF
chmod 755 "$temp/slot-dispatch" "$temp/slot-os-dispatch"
mv "$temp/slot-dispatch" /storage/slot-dispatch
mv "$temp/slot-os-dispatch" /storage/slot-os-dispatch
for unit in slot-os-guard slot-os-health; do
  sed 's|/usr/bin/slot-os-update|/storage/slot-os-dispatch|' "$temp/$unit.service" > "$temp/$unit.new"
  mv "$temp/$unit.new" "/storage/.config/system.d/$unit.service"
  ln -sf "../$unit.service" "/storage/.config/system.d/rocknix.target.wants/$unit.service"
done
cat > "$temp/managed.conf" <<'EOF'
[Unit]
Wants=slot-os-guard.service
After=slot-os-guard.service
[Service]
ExecStart=
ExecStart=/usr/bin/systemd-inhibit --what=handle-power-key --mode=block --who=Slot --why="Slot handles the power button" /storage/slot-dispatch
EOF
mv "$temp/managed.conf" /storage/.config/system.d/slot-rg353v.service.d/50-managed-updates.conf
sync
systemctl daemon-reload
echo 'Updater bootstrap installed. Slot and boot selection were left running unchanged.'
REMOTE
