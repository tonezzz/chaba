#!/usr/bin/env bash
set -euo pipefail

echo "== systemd units =="
systemctl --user is-active ada-ha-tony.service
systemctl --user is-active ada-ha-michael.service
systemctl --user is-active caddy-mn01.service

echo "== HTTP endpoints =="
curl -sf -o /dev/null -w "tony HTTP %{http_code}\n" "https://mn01.taila0626a.ts.net/apps/ada_ha_tony/" || true
curl -sf -o /dev/null -w "michael HTTP %{http_code}\n" "https://mn01.taila0626a.ts.net/apps/ada_ha_michael/" || true

echo "== WebSocket ready =="
curl -sf -o /dev/null -w "tony ws %{http_code}\n" -H "Upgrade: websocket" -H "Connection: Upgrade" "https://mn01.taila0626a.ts.net/apps/ada_ha_tony/ws" || true
curl -sf -o /dev/null -w "michael ws %{http_code}\n" -H "Upgrade: websocket" -H "Connection: Upgrade" "https://mn01.taila0626a.ts.net/apps/ada_ha_michael/ws" || true

echo "Verify complete."
