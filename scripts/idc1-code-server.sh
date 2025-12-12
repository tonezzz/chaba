#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
CODE_SERVER_MODE=${CODE_SERVER_MODE:-container}
CODE_SERVER_CONTAINER=${CODE_SERVER_CONTAINER:-idc1-code-server}
CODE_SERVER_SERVICE=${CODE_SERVER_SERVICE:-code-server}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

MODE=${1:-restart}

echo "[IDC1] Managing code-server ($CODE_SERVER_MODE) on $SSH_HOST as $SSH_USER (mode=$MODE)"

case "$MODE" in
  status)
    if [[ "$CODE_SERVER_MODE" == "systemd" ]]; then
      ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" CODE_SERVER_SERVICE="$CODE_SERVER_SERVICE" <<'EOF'
set -euo pipefail
echo "[REMOTE] systemctl status for $CODE_SERVER_SERVICE"
systemctl status "$CODE_SERVER_SERVICE" --no-pager || true
EOF
    else
      ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" CODE_SERVER_CONTAINER="$CODE_SERVER_CONTAINER" <<'EOF'
set -euo pipefail
echo "[REMOTE] docker ps status for $CODE_SERVER_CONTAINER"
docker ps --filter "name=^/${CODE_SERVER_CONTAINER}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
EOF
    fi
    ;;
  logs)
    if [[ "$CODE_SERVER_MODE" == "systemd" ]]; then
      ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" CODE_SERVER_SERVICE="$CODE_SERVER_SERVICE" <<'EOF'
set -euo pipefail
echo "[REMOTE] journalctl for $CODE_SERVER_SERVICE (last 100 lines)"
journalctl -u "$CODE_SERVER_SERVICE" -n 100 --no-pager || true
EOF
    else
      ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" CODE_SERVER_CONTAINER="$CODE_SERVER_CONTAINER" <<'EOF'
set -euo pipefail
echo "[REMOTE] docker logs for $CODE_SERVER_CONTAINER (last 100 lines)"
docker logs --tail 100 "$CODE_SERVER_CONTAINER" 2>&1 || true
EOF
    fi
    ;;
  restart)
    if [[ "$CODE_SERVER_MODE" == "systemd" ]]; then
      ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" CODE_SERVER_SERVICE="$CODE_SERVER_SERVICE" <<'EOF'
set -euo pipefail
echo "[REMOTE] Restarting $CODE_SERVER_SERVICE via systemctl restart"
sudo systemctl restart "$CODE_SERVER_SERVICE"

echo "[REMOTE] systemctl status after restart"
systemctl status "$CODE_SERVER_SERVICE" --no-pager || true

echo "[REMOTE] journalctl (last 100 lines) after restart"
journalctl -u "$CODE_SERVER_SERVICE" -n 100 --no-pager || true
EOF
    else
      ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" CODE_SERVER_CONTAINER="$CODE_SERVER_CONTAINER" <<'EOF'
set -euo pipefail
echo "[REMOTE] Restarting $CODE_SERVER_CONTAINER via docker restart"
docker restart "$CODE_SERVER_CONTAINER"

echo "[REMOTE] docker ps status after restart"
docker ps --filter "name=^/${CODE_SERVER_CONTAINER}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
EOF
    fi
    ;;
  *)
    echo "[IDC1] Unknown mode: $MODE (expected: status|logs|restart)" >&2
    exit 1
    ;;
esac

echo "[IDC1] code-server management ($MODE) completed."
