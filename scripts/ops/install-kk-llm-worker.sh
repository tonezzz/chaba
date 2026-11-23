#!/usr/bin/env bash
set -euo pipefail

# Render the user-level KK-Mac worker LaunchAgent. The default is a
# non-mutating print so a rollout can be reviewed before launchd is
# touched. Renders the CURRENT lane worker (kk_mac_lane_worker.py,
# card kk-mac-continuous-llm-worker — the 2026-11-17 cutover target),
# matching scripts/ops/net.adanest.kk-llm-worker.plist.
#
# OPS-1036 / card kk-mac-worker-idle-poll-efficiency: the interval
# default is 60s and anything below 30s is refused — the old 15s
# interval kept Ollama and rclone hot against an empty queue.

LABEL="net.adanest.kk-llm-worker"
KK_MAC_HOME="${KK_MAC_HOME:-$HOME}"
CHABA_ROOT="${CHABA_ROOT:-$KK_MAC_HOME/CascadeProjects/chaba}"
PYTHON="${KK_WORKER_PYTHON:-$KK_MAC_HOME/.cache/nest-worker/venv/bin/python}"
WORKDIR="${KK_WORKER_WORKDIR:-$KK_MAC_HOME/.cache/kk-llm-worker}"
REMOTE="${KK_WORKER_REMOTE:-gdrive:ada-nest/kk-llm}"
HOST_ARG="${KK_WORKER_HOST:-local}"
MAX_PACKS="${KK_WORKER_MAX_PACKS:-1}"
START_INTERVAL="${KK_WORKER_INTERVAL:-60}"
PLIST="$KK_MAC_HOME/Library/LaunchAgents/$LABEL.plist"
APPLY=0

usage() {
    cat <<'EOF'
Usage: install-kk-llm-worker.sh [--print] [--apply]

The default and --print render the plist without changing launchd.
--apply atomically installs the plist and reloads the user LaunchAgent.
Override paths with KK_MAC_HOME, CHABA_ROOT, KK_WORKER_PYTHON,
KK_WORKER_WORKDIR, KK_WORKER_REMOTE, KK_WORKER_HOST,
KK_WORKER_MAX_PACKS (1-2), and KK_WORKER_INTERVAL (>=30).
EOF
}

for arg in "$@"; do
    case "$arg" in
        --print) ;;
        --apply) APPLY=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

case "$START_INTERVAL" in
    ''|*[!0-9]*) echo "KK_WORKER_INTERVAL must be an integer" >&2; exit 2 ;;
esac
if (( START_INTERVAL < 30 )); then
    echo "KK_WORKER_INTERVAL must be >= 30 seconds" >&2
    exit 2
fi
case "$MAX_PACKS" in
    1|2) ;;
    *) echo "KK_WORKER_MAX_PACKS must be 1 or 2 (capacity procedure cap)" >&2
       exit 2 ;;
esac

render() {
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PYTHON</string>
    <string>$CHABA_ROOT/scripts/devnest/kk_mac_lane_worker.py</string>
    <string>--remote</string><string>$REMOTE</string>
    <string>--host</string><string>$HOST_ARG</string>
    <string>--workdir</string><string>$WORKDIR</string>
    <string>--max-packs</string><string>$MAX_PACKS</string>
  </array>
  <key>StartInterval</key><integer>$START_INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$WORKDIR/worker.log</string>
  <key>StandardErrorPath</key><string>$WORKDIR/worker.err</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$KK_MAC_HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
</dict></plist>
EOF
}

if (( ! APPLY )); then
    render
    exit 0
fi

mkdir -p "$(dirname "$PLIST")" "$WORKDIR"
tmp="$(mktemp "${PLIST}.tmp.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
render >"$tmp"
mv "$tmp" "$PLIST"

domain="gui/$(id -u)"
launchctl bootout "$domain/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$domain" "$PLIST"
launchctl kickstart -k "$domain/$LABEL"
echo "installed $PLIST (StartInterval=${START_INTERVAL}s)"
