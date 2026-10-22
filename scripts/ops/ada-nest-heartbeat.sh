#!/bin/sh
# ada-nest-heartbeat — standard phone-home for Ada Nest member devices.
#
# POSTs one upsert doc to MDDB (collection "ada-nest-heartbeats",
# key "heartbeat/<hostname>") every run. Designed for cron or a
# LaunchDaemon/systemd timer at ~5min cadence.
#
# Goes over the tailnet by default — so a successful beat proves BOTH
# "I'm online" and "my tailnet path works" (reachable while traveling).
# Silence while the host is LAN-alive => tailnet broken or host off-net.
#
# Env:  MDDB_URL   (default http://100.102.134.91:11026/v1 — idc03 tailnet)
#       NEST_ROLE  (e.g. apple-silicon-workstation)
#       HEARTBEAT_EXTRA_CMD  optional command adding a "extra" JSON field
#
# Install (macOS): deploy alongside net.adanest.heartbeat.plist.

set -u
MDDB_URL="${MDDB_URL:-http://100.102.134.91:11026/v1}"
HOST="$(hostname -s 2>/dev/null || hostname)"
ROLE="${NEST_ROLE:-member-device}"

tailnet_ip() {
  for bin in /usr/local/bin/tailscale /opt/homebrew/bin/tailscale tailscale; do
    [ -x "$bin" ] || command -v "$bin" >/dev/null 2>&1 || continue
    "$bin" ip -4 2>/dev/null | head -1 && return
  done
  echo ""
}

lan_ip() {
  ifconfig 2>/dev/null | awk '/inet / && $2 != "127.0.0.1" && $2 !~ /^169\.254/ {print $2; exit}'
}

svc_ollama() {
  curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:11434/api/version" 2>/dev/null | grep -q 200 \
    && echo true || echo false
}

tmux_jobs() {
  for bin in /opt/homebrew/bin/tmux /usr/bin/tmux tmux; do
    command -v "$bin" >/dev/null 2>&1 || continue
    "$bin" ls 2>/dev/null | cut -d: -f1 | paste -sd, - ; return
  done
  echo ""
}

disk_free_gb() {
  df -g / 2>/dev/null | awk 'NR==2 {print $4}'
}

EXTRA=""
[ -n "${HEARTBEAT_EXTRA_CMD:-}" ] && EXTRA="\"extra\": $(sh -c "$HEARTBEAT_EXTRA_CMD" 2>/dev/null || echo null),"

PAYLOAD=$(cat <<EOF
{"collection":"ada-nest-heartbeats","key":"heartbeat/$HOST","lang":"en",
"contentMd":"{\"host\":\"$HOST\",\"role\":\"$ROLE\",\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"tailnet_ip\":\"$(tailnet_ip)\",\"lan_ip\":\"$(lan_ip)\",\"ollama_ok\":$(svc_ollama),\"tmux_jobs\":\"$(tmux_jobs)\",\"disk_free_gb\":$(disk_free_gb),\"uptime_s\":$(sysctl -n kern.boottime 2>/dev/null | sed 's/.*sec = //;s/,.*//' | awk -v n=$(date +%s) '{print n-$1}' || echo 0),$EXTRA\"platform\":\"$(uname -s)\"}",
"meta":{"host":["$HOST"],"kind":["nest-heartbeat"],"ts":["$(date -u +%Y-%m-%dT%H:%M:%SZ)"]}}
EOF
)

curl -s -m 15 -o /dev/null -w "%{http_code}" -X POST "$MDDB_URL/add" \
  -H "content-type: application/json" -d "$PAYLOAD" | grep -q 200 \
  && echo "beat ok $HOST -> $MDDB_URL" || echo "beat FAILED $HOST -> $MDDB_URL"
