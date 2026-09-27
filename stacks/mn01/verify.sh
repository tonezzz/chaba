#!/usr/bin/env bash
# Post-migration (2026-09-24): Ada instances run on idc01. mn01 keeps
# ada-ha-* units stopped as standby and only proxies/serves static pages.
set -euo pipefail

echo "== systemd units =="
systemctl --user is-active caddy-mn01.service
for u in ada-ha-tony.service ada-ha-michael.service; do
  state=$(systemctl --user is-active "$u" 2>/dev/null || true)
  enabled=$(systemctl --user is-enabled "$u" 2>/dev/null || true)
  # standby = inactive + not enabled (idc01 is primary; enable only for fallback)
  echo "$u: $state/$enabled (standby expected: inactive/disabled)"
done

echo "== HTTP endpoints (edge 308 -> idc01 expected) =="
curl -s -o /dev/null -w "tony HTTP %{http_code}\n" --max-time 8 "https://mn01.taila0626a.ts.net/apps/ada_ha_tony/"
curl -s -o /dev/null -w "michael HTTP %{http_code}\n" --max-time 8 "https://mn01.taila0626a.ts.net/apps/ada_ha_michael/"

echo "== WebSocket ready =="
curl -s -o /dev/null -w "tony ws %{http_code}\n" --max-time 8 -H "Upgrade: websocket" -H "Connection: Upgrade" "https://mn01.taila0626a.ts.net/apps/ada_ha_tony/ws"
curl -s -o /dev/null -w "michael ws %{http_code}\n" --max-time 8 -H "Upgrade: websocket" -H "Connection: Upgrade" "https://mn01.taila0626a.ts.net/apps/ada_ha_michael/ws"

echo "Verify complete."
