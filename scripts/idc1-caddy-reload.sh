#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

echo "[IDC1] Reloading Caddy on $SSH_HOST as $SSH_USER"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" <<'EOF'
set -euo pipefail

reload_systemd() {
  if command -v sudo >/dev/null 2>&1; then
    sudo -n systemctl reload caddy
  else
    systemctl reload caddy
  fi
}

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet caddy 2>/dev/null; then
  reload_systemd
  echo "[REMOTE] caddy reloaded (systemd)"
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' | grep -Fxq 'idc1-caddy'; then
    docker exec idc1-caddy caddy reload --config /etc/caddy/Caddyfile --force
    echo "[REMOTE] caddy reloaded (docker idc1-caddy)"
    exit 0
  fi
fi

echo "[REMOTE] Could not reload Caddy: systemd caddy inactive and docker container idc1-caddy not running" >&2
exit 2
EOF

echo "[IDC1] caddy reload completed."
