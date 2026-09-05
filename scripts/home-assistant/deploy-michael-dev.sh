#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." &>/dev/null && pwd)
HA_DIR="$REPO_ROOT/docs/home-assistant"

DEV_CONFIG="${MICHAEL_DEV_CONFIG:-$HOME/.config/michael-dev}"
DEV_SERVICE="${MICHAEL_DEV_SERVICE:-michael-dev.service}"
DEV_PORT="${MICHAEL_DEV_PORT:-8124}"
DEPLOY_DASHBOARDS="${MICHAEL_DEPLOY_DASHBOARDS:-0}"
MCP_URL="${MICHAEL_DEV_MCP_URL:-http://127.0.0.1:9585/private_B3WMIAChoseTpDS7fwgwRw}"

log() { echo "[deploy-michael-dev] $*"; }

HA_MCP_CALL="$REPO_ROOT/scripts/home-assistant/ha-mcp-call.py"
if [ ! -f "$HA_MCP_CALL" ]; then
  log "HA-MCP helper not found: $HA_MCP_CALL"
  exit 1
fi

if [ ! -d "$HA_DIR/configuration" ]; then
  log "Repo HA config not found: $HA_DIR/configuration"
  exit 1
fi

log "Ensuring dev config directory exists: $DEV_CONFIG"
mkdir -p "$DEV_CONFIG"

log "Deploying packages and helpers to $DEV_CONFIG"
rsync -avz "$HA_DIR/configuration/" "$DEV_CONFIG/"

DEV_MOCKS="$HA_DIR/dev/dev-mocks.yaml"
if [ -f "$DEV_MOCKS" ]; then
  log "Deploying dev mock entities to $DEV_CONFIG/packages/a_dev_mocks.yaml"
  mkdir -p "$DEV_CONFIG/packages"
  cp "$DEV_MOCKS" "$DEV_CONFIG/packages/a_dev_mocks.yaml"
fi

if [ "$DEPLOY_DASHBOARDS" -eq 1 ] && [ -d "$HA_DIR/dashboards" ]; then
  log "Deploying dashboard files to $DEV_CONFIG/lovelace/"
  mkdir -p "$DEV_CONFIG/lovelace"
  rsync -avz "$HA_DIR/dashboards/" "$DEV_CONFIG/lovelace/"
else
  log "Skipping dashboards. Set MICHAEL_DEPLOY_DASHBOARDS=1 to rsync dashboards/ to $DEV_CONFIG/lovelace/"
fi

if systemctl --user is-active "$DEV_SERVICE" >/dev/null 2>&1; then
  log "Reloading core config via HA-MCP ($MCP_URL)"
  python3 "$HA_MCP_CALL" --url "$MCP_URL" --tool ha_reload_core
else
  log "Service $DEV_SERVICE not active; loading and starting it"
  systemctl --user daemon-reload
  systemctl --user start "$DEV_SERVICE"
fi

log "Waiting for HA to respond on http://127.0.0.1:$DEV_PORT"
for i in {1..60}; do
  if curl -sf "http://127.0.0.1:$DEV_PORT/" >/dev/null 2>&1; then
    log "Home Assistant dev is reachable (HTTP 200)"
    exit 0
  fi
  sleep 1
done

log "Home Assistant dev did not become reachable within 60 seconds"
exit 1
