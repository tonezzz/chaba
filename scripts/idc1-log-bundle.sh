#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
BUNDLE_DIR=${BUNDLE_DIR:-/tmp}
BUNDLE_PREFIX=${BUNDLE_PREFIX:-idc1-log-bundle}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

CONTAINERS_DEFAULT=(
  mcp0
  mcp-agents
  mcp-devops
  mcp-tester
  mcp-glama
  idc1-code-server
)

CONTAINER_LIST=()
if [[ -n "${CONTAINERS:-}" ]]; then
  IFS=',' read -r -a CONTAINER_LIST <<<"${CONTAINERS}"
else
  CONTAINER_LIST=("${CONTAINERS_DEFAULT[@]}")
fi

REMOTE_CONTAINER_LIST=$(printf '%s\n' "${CONTAINER_LIST[@]}")

echo "[IDC1] Collecting log bundle from $SSH_HOST as $SSH_USER"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" BUNDLE_DIR="$BUNDLE_DIR" BUNDLE_PREFIX="$BUNDLE_PREFIX" REMOTE_CONTAINERS="$REMOTE_CONTAINER_LIST" <<'EOF'
set -euo pipefail

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR="$BUNDLE_DIR/${BUNDLE_PREFIX}-${TS}"
mkdir -p "$OUT_DIR"

{
  echo "timestamp_utc=${TS}"
  echo "hostname=$(hostname)"
  echo "uname=$(uname -a)"
  echo "uptime=$(uptime)"
} >"$OUT_DIR/meta.txt" 2>/dev/null || true

{
  echo "# df -h"
  df -h
  echo
  echo "# free -h"
  free -h || true
} >"$OUT_DIR/system.txt" 2>/dev/null || true

(docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}' >"$OUT_DIR/docker-ps.txt") 2>/dev/null || true
(docker network ls >"$OUT_DIR/docker-network-ls.txt") 2>/dev/null || true

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  for stack in "/home/chaba/chaba/stacks/idc1-stack" "/workspaces/chaba/stacks/idc1-stack"; do
    if [ -f "$stack/docker-compose.yml" ]; then
      (cd "$stack" && docker compose ps >"$OUT_DIR/idc1-stack-compose-ps.txt") 2>/dev/null || true
      break
    fi
  done
fi

while IFS= read -r name; do
  name=$(echo "$name" | tr -d '\r')
  if [ -z "$name" ]; then
    continue
  fi

  if docker inspect "$name" >/dev/null 2>&1; then
    (docker logs --timestamps --tail 1000 "$name" >"$OUT_DIR/${name}.docker.log" 2>&1) || true
    (docker inspect "$name" >"$OUT_DIR/${name}.inspect.json" 2>&1) || true
  else
    echo "Container '$name' not found" >"$OUT_DIR/${name}.missing.txt"
  fi
done <<<"$REMOTE_CONTAINERS"

(systemctl status caddy --no-pager >"$OUT_DIR/caddy.status.txt" 2>&1) || true
(journalctl -u caddy -n 300 --no-pager >"$OUT_DIR/caddy.journal.txt" 2>&1) || true

TARBALL="$OUT_DIR.tar.gz"
(tar -C "$(dirname "$OUT_DIR")" -czf "$TARBALL" "$(basename "$OUT_DIR")") 2>/dev/null || true

echo "[REMOTE] Bundle directory: $OUT_DIR"
echo "[REMOTE] Bundle tarball: $TARBALL"
EOF

echo "[IDC1] Log bundle collection completed."
