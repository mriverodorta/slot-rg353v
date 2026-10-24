#!/bin/sh
set -eu
SYS=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=${SLOT_ROOT:-$(dirname "$SYS")}
file="$ROOT/.slot-display-services"
[ -f "$file" ] || exit 0
units=''
for unit in $(cat "$file"); do
    case "$unit" in
        emustation.service|essway.service|sway.service) units="$units $unit" ;;
        *) echo "Unexpected restore unit: $unit" >&2; exit 2 ;;
    esac
done
if [ -n "$units" ]; then
    systemctl start --no-block $units
    : > "$file"
fi
