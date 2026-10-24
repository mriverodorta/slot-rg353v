#!/bin/sh
# Read-only device survey. Does not dump environment, Wi-Fi configuration or keys.
section() { printf '\n[%s]\n' "$1"; }
section system
uname -a
for f in /etc/os-release /etc/rocknix-release /proc/device-tree/model /proc/cmdline; do
    if [ -r "$f" ]; then printf '%s: ' "$f"; tr '\000' '\n' < "$f"; printf '\n'; fi
done
section graphics
ls -l /dev/dri /dev/fb* 2>/dev/null
for d in /sys/class/drm/card*-*; do
    [ -d "$d" ] || continue
    printf '%s\n' "$d"
    for f in status modes enabled; do [ ! -r "$d/$f" ] || cat "$d/$f"; done
done
section input
for d in /sys/class/input/event*/device; do
    [ -d "$d" ] || continue
    printf '%s\n' "$d"
    for f in name capabilities/key capabilities/abs capabilities/sw; do
        if [ -r "$d/$f" ]; then printf '%s: ' "$f"; cat "$d/$f"; fi
    done
done
section power
for d in /sys/class/backlight/* /sys/class/power_supply/* /sys/class/leds/*; do
    [ -d "$d" ] || continue
    printf '%s\n' "$d"
    for f in type capacity status brightness max_brightness; do
        if [ -r "$d/$f" ]; then printf '%s: ' "$f"; cat "$d/$f"; fi
    done
done
section audio
cat /proc/asound/cards 2>/dev/null
command -v aplay >/dev/null 2>&1 && aplay -L
command -v amixer >/dev/null 2>&1 && amixer scontrols
section runtime
getconf GNU_LIBC_VERSION 2>/dev/null
ls /usr/lib/libSDL2* /usr/lib/libEGL* /usr/lib/libGLESv2* /usr/lib/libgbm* /usr/lib/libasound* 2>/dev/null
if command -v systemctl >/dev/null 2>&1; then
    systemctl --no-pager --plain list-units --type=service --state=running
fi
exit 0
