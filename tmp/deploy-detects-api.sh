#!/usr/bin/env bash
set -euo pipefail

KEY=${KEY:-/home/tonezzz/.ssh/chaba_ed25519}
HOST=${HOST:-chaba@a1.idc1.surf-thailand.com}
SRC=${SRC:-/mnt/c/chaba/sites/a1-idc1/api/detects/}
REMOTE_BASE=${REMOTE_BASE:-/www/a1.idc1.surf-thailand.com/a1-idc1/detects-api}
TS=$(date -u +%Y%m%dT%H%M%SZ)
RELEASE="$REMOTE_BASE/releases/$TS"

echo "[detects-api] syncing to $RELEASE"
ssh -i "$KEY" "$HOST" "mkdir -p '$REMOTE_BASE/releases' '$REMOTE_BASE/logs' '$REMOTE_BASE/run'"
rsync -az --delete -e "ssh -i $KEY" "$SRC" "$HOST:$RELEASE/"

echo "[detects-api] installing dependencies and restarting service"
ssh -i "$KEY" "$HOST" "REMOTE_BASE='$REMOTE_BASE' RELEASE='$RELEASE' bash -s" <<'EOF'
set -euo pipefail
cd "$RELEASE"
if [ -f package.json ]; then
  npm install --production --no-audit --no-fund
else
  echo "package.json missing in $RELEASE" >&2
  exit 1
fi
if [ -f "$REMOTE_BASE/run/api.pid" ]; then
  OLD_PID=$(cat "$REMOTE_BASE/run/api.pid" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" || true
    sleep 1
  fi
fi
PORT=${PORT:-4120} NODE_ENV=production nohup npm run start > "$REMOTE_BASE/logs/api.log" 2>&1 &
echo $! > "$REMOTE_BASE/run/api.pid"
ln -sfn "$RELEASE" "$REMOTE_BASE/current"
echo "detects-api started release $RELEASE (pid $(cat "$REMOTE_BASE/run/api.pid"))"
EOF
