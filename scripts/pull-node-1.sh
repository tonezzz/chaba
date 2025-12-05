#!/bin/bash
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/www/node-1.h3.surf-thailand.com/current}
NODE_DOMAIN=${NODE_DOMAIN:-node-1.h3.surf-thailand.com}
TARGET_REF=${TARGET_REF:-origin/node-1}

export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
GIT_BIN=$(command -v git)
NPM_BIN=$(command -v npm)

if [[ -z "$GIT_BIN" ]]; then
  echo "[pull-node-1] git not found in PATH" >&2
  exit 1
fi
if [[ -z "$NPM_BIN" ]]; then
  echo "[pull-node-1] npm not found in PATH" >&2
  exit 1
fi

cd "$PROJECT_DIR"

echo "[pull-node-1] fetching latest" && "$GIT_BIN" fetch origin

echo "[pull-node-1] resetting to $TARGET_REF" && "$GIT_BIN" reset --hard "$TARGET_REF"

if [ -f package.json ]; then
  echo "[pull-node-1] npm install --production"
  "$NPM_BIN" install --production --no-audit --no-fund
fi

if [ -f package.json ] && "$NPM_BIN" run | grep -q '^  build'; then
  echo "[pull-node-1] npm run build"
  "$NPM_BIN" run build
fi

if command -v plesk >/dev/null 2>&1; then
  echo "[pull-node-1] restarting node domain" && plesk bin nodejs --restart "$NODE_DOMAIN" || true
fi

echo "[pull-node-1] completed"
