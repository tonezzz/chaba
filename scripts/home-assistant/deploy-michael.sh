#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." &>/dev/null && pwd)
HA_DIR="$REPO_ROOT/docs/home-assistant"

REMOTE_HOST="${MICHAEL_REMOTE_HOST:-michael-ha}"
REMOTE_USER="${MICHAEL_REMOTE_USER:-root}"
REMOTE_PORT="${MICHAEL_REMOTE_PORT:-22}"
REMOTE_CONFIG="${MICHAEL_REMOTE_CONFIG:-/config}"
TOKEN_FILE="${MICHAEL_HA_TOKEN:-$HOME/.local/share/home-assistant-michael/ha-token}"
DEPLOY_DASHBOARDS="${MICHAEL_DEPLOY_DASHBOARDS:-0}"

log() { echo "[deploy-michael] $*"; }

if [ ! -f "$TOKEN_FILE" ]; then
  log "HA token not found: $TOKEN_FILE"
  exit 1
fi

log "Checking tailnet reachability to $REMOTE_HOST"
tailscale ping -c 1 "$REMOTE_HOST"

log "Checking SSH to $REMOTE_USER@$REMOTE_HOST:$REMOTE_PORT"
if ! ssh -o ConnectTimeout=5 -p "$REMOTE_PORT" "$REMOTE_USER@$REMOTE_HOST" true 2>/dev/null; then
  log "SSH not available. Install the SSH & Web Terminal add-on on $REMOTE_HOST and configure an SSH key."
  exit 1
fi

log "Deploying packages and helpers to $REMOTE_USER@$REMOTE_HOST:$REMOTE_CONFIG"
rsync -avz "$HA_DIR/configuration/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_CONFIG/"

if [ "$DEPLOY_DASHBOARDS" -eq 1 ] && [ -d "$HA_DIR/dashboards" ]; then
  log "Deploying dashboard files to $REMOTE_USER@$REMOTE_HOST:$REMOTE_CONFIG/lovelace/"
  rsync -avz "$HA_DIR/dashboards/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_CONFIG/lovelace/"
else
  log "Skipping dashboards. Set MICHAEL_DEPLOY_DASHBOARDS=1 to rsync dashboards/ to $REMOTE_CONFIG/lovelace/"
fi

log "Reloading Home Assistant core config"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST \
  -H "Authorization: Bearer $(cat "$TOKEN_FILE")" \
  -H "Content-Type: application/json" \
  "http://$REMOTE_HOST:8123/api/services/homeassistant/reload_core_config")

if [ "$HTTP_CODE" -eq 200 ]; then
  log "Home Assistant config reload triggered (HTTP $HTTP_CODE)"
else
  log "Home Assistant config reload failed (HTTP $HTTP_CODE)"
  exit 1
fi
