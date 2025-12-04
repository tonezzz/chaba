#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-/www/node-1.h3.surf-thailand.com}
NODE_DOMAIN=${NODE_DOMAIN:-node-1.h3.surf-thailand.com}
TARGET_REF=${TARGET_REF:-origin/node-1}

cd "$PROJECT_DIR"

echo "[pull-node-1] fetching latest" && git fetch origin

echo "[pull-node-1] resetting to $TARGET_REF" && git reset --hard "$TARGET_REF"

if [ -f package.json ]; then
  echo "[pull-node-1] npm install --production"
  npm install --production --no-audit --no-fund
fi

if [ -f package.json ] && npm run | grep -q '^  build'; then
  echo "[pull-node-1] npm run build"
  npm run build
fi

if command -v plesk >/dev/null 2>&1; then
  echo "[pull-node-1] restarting node domain" && plesk bin nodejs --restart "$NODE_DOMAIN" || true
fi

echo "[pull-node-1] completed"
