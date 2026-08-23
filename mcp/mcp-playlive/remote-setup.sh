#!/bin/bash
set -e
export PATH=/home/tony/.local/node/bin:$PATH
cd /home/tony/.local/playlive
if [ ! -d node_modules/playwright ]; then
  npm init -y
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install playwright
fi
pkill -f playlived.mjs 2>/dev/null || true
nohup node playlived.mjs > playlived.log 2>&1 &
sleep 2
echo "=== playlived log ==="
cat playlived.log
