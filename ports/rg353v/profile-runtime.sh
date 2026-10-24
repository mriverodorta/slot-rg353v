#!/bin/sh
# Read-only sampler. Stream results to the host; no ROMs, passwords or config contents.
set -eu
samples=${1:-30}
interval=${2:-2}
case "$samples:$interval" in *[!0-9:]*|:*) exit 2;; esac
slot_pid() {
    for f in /proc/[0-9]*/comm; do
        if [ "$(cat "$f" 2>/dev/null)" = slot ]; then
            p=${f#/proc/}; printf '%s\n' "${p%/comm}"; return
        fi
    done
    printf '0\n'
}
printf 'META\n' 
uname -a
getconf CLK_TCK
getconf _NPROCESSORS_ONLN
systemctl --no-pager --plain list-units --type=service --state=running
pid=$(slot_pid)
if [ "$pid" -gt 0 ]; then sha256sum "/proc/$pid/exe"; fi
printf 'PROCESS_SNAPSHOT\n'
ps -eo pid,comm,rss --sort=-rss | head -21
printf 'ENDMETA\n'
n=0
while [ "$n" -le "$samples" ]; do
    printf 'SAMPLE\n'
    printf 'UPTIME '; cut -d ' ' -f 1 /proc/uptime
    printf 'CPU '; head -1 /proc/stat
    printf 'MEM\n'; cat /proc/meminfo
    printf 'VM\n'; awk '/^(pswpin|pswpout|pgmajfault) /' /proc/vmstat
    printf 'PSI\n'; cat /proc/pressure/memory 2>/dev/null || true
    if [ "$pid" -eq 0 ] || [ ! -r "/proc/$pid/status" ]; then pid=$(slot_pid); fi
    printf 'PID %s\n' "$pid"
    if [ "$pid" -gt 0 ] && [ -r "/proc/$pid/status" ]; then
        printf 'PROCESS\n'; awk '/^(VmRSS|VmHWM|VmSwap|Threads):/' "/proc/$pid/status"
        # Drop pid and parenthesized comm; utime/stime are now fields 12/13.
        printf 'TICKS '; sed 's/^[0-9]* (.*) //' "/proc/$pid/stat" | awk '{print $12+$13}'
        printf 'PSS\n'; awk '/^(Pss|Private_Clean|Private_Dirty|Swap):/' "/proc/$pid/smaps_rollup" 2>/dev/null || true
    fi
    for f in /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq /sys/class/thermal/thermal_zone*/temp; do
        [ ! -r "$f" ] || printf 'SYS %s %s\n' "$f" "$(cat "$f")"
    done
    printf 'END\n'
    n=$((n+1))
    [ "$n" -gt "$samples" ] || sleep "$interval"
done
