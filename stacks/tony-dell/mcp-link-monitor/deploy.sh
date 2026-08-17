#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REMOTE="tony-dell"

echo "[deploy] syncing mcp-link-monitor systemd unit to $REMOTE"
rsync -avP mcp-link-monitor.service "$REMOTE:/home/tony/chaba-funnel/"

echo "[deploy] installing and restarting mcp-link-monitor"
ssh "$REMOTE" "mkdir -p ~/.config/systemd/user && cp /home/tony/chaba-funnel/mcp-link-monitor.service ~/.config/systemd/user/mcp-link-monitor.service && systemctl --user daemon-reload && systemctl --user restart mcp-link-monitor.service"

echo "[deploy] verifying link-monitor status"
ssh "$REMOTE" "systemctl --user is-active mcp-link-monitor.service"

echo "[deploy] done"
