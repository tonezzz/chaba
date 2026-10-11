#!/usr/bin/env bash
# incident-capture.sh — bundle everything needed to debug a wedge/dark-screen/crash.
# Run AT SYMPTOM TIME — over ssh if the console is dead (`ssh macbook`,
# `bash .../incident-capture.sh`). Evidence that is per-boot or self-destructing
# (amdgpu devcoredump is consumed on read; journal rotates) is captured first.
# Output: ~/incidents/<timestamp>/ + a .tar.gz alongside it.
set -uo pipefail
ts=$(date +%Y%m%d-%H%M%S)
out="$HOME/incidents/$ts"
mkdir -p "$out"
say() { printf '%s\n' "$*"; }

say "== meta =="
{ date; uptime; uname -a; hostname
  echo "cmdline: $(cat /proc/cmdline)"
  journalctl --list-boots --no-pager | tail -3
} > "$out/meta.txt"

say "== devcoredump (consumed on read — captured first) =="
found=0
for d in /sys/class/drm/card?/device/devcoredump/data /sys/class/devcoredump/devcd*/data; do
  [ -e "$d" ] || continue
  card=$(echo "$d" | grep -oE "card[0-9]+" | head -1)
  cp "$d" "$out/devcoredump-${card:-gpu}.bin" 2>/dev/null \
    && { say "   captured $d"; found=1; } \
    || say "   FAILED to read $d"
done
[ "$found" = 0 ] && echo "none present (normal unless a GPU reset just happened)" > "$out/devcoredump.txt"

say "== display/gpu state =="
{ for c in /sys/class/drm/card?-*/{status,enabled}; do
    [ -e "$c" ] && echo "$c = $(cat "$c" 2>/dev/null)"
  done
  command -v gdctl >/dev/null && { echo "--- gdctl show ---"; gdctl show; }
  echo "--- gpu busy/reset counters ---"
  for f in /sys/class/drm/card?/device/gpu_busy_percent /sys/class/drm/card?/device/reset_counter; do
    [ -e "$f" ] && echo "$f = $(cat "$f")"
  done
} > "$out/gpu-display.txt" 2>&1

say "== journals =="
journalctl -b    --no-pager -n 3000 > "$out/journal-this-boot.txt" 2>&1
journalctl -b -1 --no-pager -n 3000 > "$out/journal-prev-boot.txt" 2>&1
journalctl -k -b --no-pager        > "$out/kern-this-boot.txt"    2>&1

say "== system state =="
{ systemctl list-units --state=failed --no-legend --all 2>/dev/null
  systemctl --user list-units --state=failed --no-legend --all 2>/dev/null
  echo "--- sensors ---"; command -v sensors >/dev/null && sensors
  echo "--- mem/disk ---"; free -h; df -h / /home 2>/dev/null
  echo "--- top cpu ---"; ps aux --sort=-%cpu | head -15
  echo "--- coredumpctl ---"; coredumpctl list --no-pager 2>/dev/null | tail -20
} > "$out/system.txt"

say "== scalecheck state (if present) =="
SC="${DISPLAY_SCALE_CHECK:-$HOME/.local/bin/display-scale-check}"
[ -x "$SC" ] && "$SC" > "$out/scalecheck.txt" 2>&1 || true

tar -czf "$out.tar.gz" -C "$HOME/incidents" "$ts" && say "bundle: $out.tar.gz"
say "done -> $out"
