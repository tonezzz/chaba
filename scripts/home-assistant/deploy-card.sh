#!/usr/bin/env bash
# Build + deploy the forked sunsynk-power-flow-card to michael-dev.
# Version is derived from the remote lovelace_resources (single source of truth)
# so parallel sessions cannot collide on "next version".
set -euo pipefail

CARD_REPO="${CARD_REPO:-/home/tony/CascadeProjects/sunsynk-power-flow-card}"
HOST="${HOST:-tony-dell}"
WWW="/home/tony/.config/michael-dev/www"
RES="/home/tony/.config/michael-dev/.storage/lovelace_resources"
BASE="sunsynk-power-flow-card-fork"
URL_BASE="https://tony-dell.taila0626a.ts.net:8124"

cd "$CARD_REPO"
npm run build

cur=$(ssh "$HOST" "grep -o '${BASE}-v[0-9]*' '$RES' | head -1 | grep -o '[0-9]*$'")
[ -n "$cur" ] || { echo "ERROR: no existing ${BASE}-vN resource on $HOST:$RES"; exit 1; }
next=$((cur + 1))
file="${BASE}-v${next}.js"
echo "current: v$cur -> deploying v$next"

scp "dist/sunsynk-power-flow-card.js" "$HOST:$WWW/$file"
ssh "$HOST" "sed -i 's|${BASE}-v[0-9]*\.js|${file}|g' '$RES' && systemctl --user restart michael-dev.service"

echo -n "waiting for HA..."
for i in $(seq 1 40); do
  code=$(curl -sk -o /dev/null -w '%{http_code}' "$URL_BASE/local/$file" || true)
  [ "$code" = "200" ] && break
  sleep 3
done
echo " $code"
[ "$code" = "200" ] || { echo "ERROR: bundle not served after restart"; exit 1; }
echo "deployed /local/$file"
