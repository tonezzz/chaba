#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
MCP0_PORT=${MCP0_PORT:-8355}
MCP_AGENTS_PORT=${MCP_AGENTS_PORT:-8046}
MCP_DEVOPS_PORT=${MCP_DEVOPS_PORT:-8425}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" MCP0_PORT="$MCP0_PORT" MCP_AGENTS_PORT="$MCP_AGENTS_PORT" MCP_DEVOPS_PORT="$MCP_DEVOPS_PORT" <<'EOF'
set -euo pipefail
function check() {
  local label=$1
  local url=$2
  echo "[REMOTE] Checking ${label}: ${url}"
  if curl -fsSL -w "\nHTTP_STATUS:%{http_code}\n" "$url"; then
    echo "[REMOTE] ${label} healthy."
  else
    echo "[REMOTE] ${label} FAILED."
  fi
  echo
}
check "mcp0" "http://127.0.0.1:${MCP0_PORT}/health"
check "mcp-agents" "http://127.0.0.1:${MCP_AGENTS_PORT}/health"
check "mcp-devops" "http://127.0.0.1:${MCP_DEVOPS_PORT}/health"
EOF

echo "[IDC1] Health sweep completed."
