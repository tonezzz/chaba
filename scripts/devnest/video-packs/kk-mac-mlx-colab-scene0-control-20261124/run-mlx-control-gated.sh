#!/bin/bash
# run-mlx-control-gated.sh — gated one-shot launcher for the KK-Mac MLX
# video control pack (card kk-mac-video-library-rerender).
#
# Polls the owner-use/idle/load/memory gates locally (no Drive calls in
# the poll loop), writes a heartbeat to the video-pilot queue, and only
# then runs nest-worker --once against gdrive:ada-nest/kk-mac-video-pilot.
# nest-worker claims serially -> concurrency=1. The pack's own prep
# re-checks the same gates at claim time.
#
# Stop:  tmux kill-session -t mlx-control
# Log:   ~/kk-video/logs/mlx-control-gated.log
# Max wait: 12h, then exits (pack stays queued for a later run).

set -u
PACK="kk-mac-mlx-colab-scene0-control-20261124"
REMOTE="gdrive:ada-nest/kk-mac-video-pilot"
RCLONE="$HOME/.local/bin/rclone"
PY="$HOME/kk-video/.venv-mlx/bin/python"
CHABA="$HOME/CascadeProjects/chaba"
LOGDIR="$HOME/kk-video/logs"
LOG="$LOGDIR/mlx-control-gated.log"
WORKER_PY="$CHABA/scripts/ada/nest-worker.py"
MAX_WAIT_S=43200
POLL_S=120
HEARTBEAT_EVERY=5   # polls between heartbeat writes (~10min)

mkdir -p "$LOGDIR"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

say "gated launcher start pack=$PACK pid=$$"

# already resolved? don't re-run a finished pack
if "$RCLONE" lsf "$REMOTE/packs/$PACK/done" >/dev/null 2>&1 \
   || "$RCLONE" lsf "$REMOTE/packs/$PACK/failed" >/dev/null 2>&1; then
  say "pack already has done/failed marker — exiting"
  exit 0
fi

gates_green() {
  # owner-use stop gate: >=10min since last HID input
  IDLE_NS=$(ioreg -c IOHIDSystem 2>/dev/null | awk '/HIDIdleTime/ {print $NF}' | head -1)
  case "$IDLE_NS" in ''|*[!0-9]*) return 1;; esac
  [ $((IDLE_NS / 1000000000)) -ge 600 ] || return 1
  # AC power
  pmset -g batt 2>/dev/null | grep -q "AC Power" || return 1
  # memory free >= 40%
  FREE_PCT=$(memory_pressure 2>/dev/null | awk -F'[:%]' '/System-wide memory free percentage:/ {gsub(/[[:space:]]/, "", $2); print $2}')
  case "$FREE_PCT" in ''|*[!0-9]*) return 1;; esac
  [ "$FREE_PCT" -ge 40 ] || return 1
  # no big resident model runner (>10GB RSS; small embeds like bge-m3 ok)
  BIG=$(ps -axo rss=,command= 2>/dev/null | awk '/llama-server/ && $1+0 > 10485760 {n++} END{print n+0}')
  [ "${BIG:-0}" -eq 0 ] || return 1
  # load1 < 8
  LOAD1=$(sysctl -n vm.loadavg 2>/dev/null | awk '{print $2}')
  awk -v l="$LOAD1" 'BEGIN{exit !(l+0 < 8.0)}' || return 1
  # no creative/video owner apps
  BUSY=$(ps -axo comm 2>/dev/null | awk '{s=tolower($0); sub(/^.*\//, "", s); if(s ~ /^(ffmpeg|resolve|davinci resolve|premiere pro|adobe premiere pro|final cut pro|after effects|photoshop|blender|unreal editor)$/) n++} END {print n+0}')
  [ "${BUSY:-1}" -eq 0 ] || return 1
  # disk >= 5GB
  AVAIL_KB=$(df -k "$HOME" 2>/dev/null | awk 'NR==2{print $4}')
  [ "${AVAIL_KB:-0}" -ge 5242880 ] || return 1
  return 0
}

heartbeat() {
  # best-effort; never blocks the gate loop
  "$RCLONE" rcat "$REMOTE/queue/heartbeat" \
    <<<"$(date +%s) mlx-control-gated waiting pid=$$" >/dev/null 2>&1 || true
}

i=0
while :; do
  if gates_green; then
    say "gates GREEN — launching nest-worker --once"
    heartbeat
    cd "$CHABA" || { say "chaba checkout missing"; exit 1; }
    "$PY" "$WORKER_PY" --remote "$REMOTE" \
      --workdir "$HOME/.cache/nest-worker" --once >> "$LOG" 2>&1
    rc=$?
    say "nest-worker exit rc=$rc"
    heartbeat
    exit $rc
  fi
  i=$((i+1))
  if [ $((i % HEARTBEAT_EVERY)) -eq 1 ]; then
    say "waiting: gates not green (poll $i)"
    heartbeat
  fi
  [ $((i * POLL_S)) -ge "$MAX_WAIT_S" ] && { say "max wait ${MAX_WAIT_S}s reached — exiting, pack stays queued"; exit 2; }
  sleep "$POLL_S"
done
