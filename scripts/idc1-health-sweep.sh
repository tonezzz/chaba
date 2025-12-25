#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
ONE_MCP_PORT=${ONE_MCP_PORT:-3050}
MCP_AGENTS_PORT=${MCP_AGENTS_PORT:-8446}
MCP_DEVOPS_PORT=${MCP_DEVOPS_PORT:-8425}
MCP_PLAYWRIGHT_PORT=${MCP_PLAYWRIGHT_PORT:-8460}
MCP_MEMORY_PORT=${MCP_MEMORY_PORT:-8470}
MCP_TESTER_PORT=${MCP_TESTER_PORT:-8435}
MCP_GLAMA_PORT=${MCP_GLAMA_PORT:-7441}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" ONE_MCP_PORT="$ONE_MCP_PORT" MCP_AGENTS_PORT="$MCP_AGENTS_PORT" MCP_DEVOPS_PORT="$MCP_DEVOPS_PORT" MCP_PLAYWRIGHT_PORT="$MCP_PLAYWRIGHT_PORT" MCP_MEMORY_PORT="$MCP_MEMORY_PORT" MCP_TESTER_PORT="$MCP_TESTER_PORT" MCP_GLAMA_PORT="$MCP_GLAMA_PORT" <<'EOF'
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
check "1mcp-agent" "http://127.0.0.1:${ONE_MCP_PORT}/health/ready"
check "mcp-agents" "http://127.0.0.1:${MCP_AGENTS_PORT}/health"
check "mcp-devops" "http://127.0.0.1:${MCP_DEVOPS_PORT}/health"
check "mcp-playwright" "http://127.0.0.1:${MCP_PLAYWRIGHT_PORT}/health"
check "mcp-memory" "http://127.0.0.1:${MCP_MEMORY_PORT}/health"
check "mcp-tester" "http://127.0.0.1:${MCP_TESTER_PORT}/health"
check "mcp-glama" "http://127.0.0.1:${MCP_GLAMA_PORT}/health"
EOF

echo "[IDC1] Health sweep completed."
