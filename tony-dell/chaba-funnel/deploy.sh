#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REMOTE="tony-dell"
REMOTE_DIR="/home/tony/chaba-funnel"

echo "[deploy] syncing funnel server to $REMOTE:$REMOTE_DIR"
rsync -avP funnel-server.py index.html "$REMOTE:$REMOTE_DIR/"

echo "[deploy] syncing docs from chaba-h3/public/apps/docs/"
rsync -avP ../../../chaba-h3/public/apps/docs/ "$REMOTE:$REMOTE_DIR/public/apps/docs/"

echo "[deploy] syncing systemd unit"
rsync -avP chaba-funnel.service "$REMOTE:$REMOTE_DIR/"

echo "[deploy] installing and restarting service"
ssh "$REMOTE" "mkdir -p ~/.config/systemd/user && cp $REMOTE_DIR/chaba-funnel.service ~/.config/systemd/user/chaba-funnel.service && systemctl --user daemon-reload && systemctl --user restart chaba-funnel.service"

echo "[deploy] verifying health"
curl -s -o /dev/null -w '%{http_code}\n' https://tony-dell.taila0626a.ts.net/health
curl -s -o /dev/null -w '%{http_code}\n' https://tony-dell.taila0626a.ts.net/apps/docs/index.html

echo "[deploy] done"
