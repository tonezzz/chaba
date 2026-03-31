#!/usr/bin/env bash
set -euo pipefail

fail=0

check() {
  local name="$1"
  local cmd="$2"
  printf '== %s ==\n' "$name"
  if bash -lc "$cmd"; then
    echo "ok"
  else
    echo "fail"
    fail=1
  fi
  echo
}

check "local jarvis-backend health" "curl --max-time 5 -fsS http://127.0.0.1:18018/health >/dev/null"
check "local jarvis-frontend" "curl --max-time 5 -fsS -I http://127.0.0.1:18080/jarvis/ | head -n 1 | grep -q ' 200 '"
check "local deep-research-worker health" "curl --max-time 5 -fsS http://127.0.0.1:18030/health >/dev/null"
check "local mcp-bundle health" "curl --max-time 5 -fsS http://127.0.0.1:3051/health >/dev/null"
check "local mcp-ws-gateway health" "curl --max-time 5 -fsS http://127.0.0.1:18182/health >/dev/null"
check "local mcp-ws-gateway-portainer health" "curl --max-time 5 -fsS http://127.0.0.1:18183/health >/dev/null"

check "public jarvis UI" "curl --max-time 10 -fsS -I https://assistance.idc1.surf-thailand.com/jarvis/ | head -n 1 | grep -q ' 200'"
check "public jarvis OpenAPI" "curl --max-time 10 -fsS -I https://assistance.idc1.surf-thailand.com/jarvis/api/openapi.json | head -n 1 | grep -q ' 200'"

if command -v python3 >/dev/null 2>&1; then
  if python3 -c 'import websockets' >/dev/null 2>&1; then
    check "public jarvis websocket handshake" "python3 scripts/ws_smoke_test.py --url wss://assistance.idc1.surf-thailand.com/jarvis/ws/live --timeout 10"
  fi
fi

if [[ "$fail" == "0" ]]; then
  echo "ALL_OK"
  exit 0
fi

echo "SOME_CHECKS_FAILED" >&2
exit 1
