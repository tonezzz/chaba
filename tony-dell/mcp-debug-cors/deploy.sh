#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REMOTE="tony-dell"

echo "[deploy] syncing mcp-debug-cors systemd unit to $REMOTE"
rsync -avP mcp-debug-cors.service "$REMOTE:/home/tony/chaba-funnel/"

echo "[deploy] installing and restarting mcp-debug-cors"
ssh "$REMOTE" "mkdir -p ~/.config/systemd/user && cp /home/tony/chaba-funnel/mcp-debug-cors.service ~/.config/systemd/user/mcp-debug-cors.service && systemctl --user daemon-reload && systemctl --user restart mcp-debug-cors.service"

echo "[deploy] verifying CORS endpoint"
curl -s -o /dev/null -w '%{http_code}\n' https://tony-dell.taila0626a.ts.net/mcp-savings.json

echo "[deploy] done"
