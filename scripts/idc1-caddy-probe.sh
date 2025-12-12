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

echo "[IDC1] Probing Caddy configuration on $SSH_HOST as $SSH_USER"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" <<'EOF'
set -euo pipefail

echo "== hostname =="
hostname

echo

echo "== caddy service (systemd) =="
(systemctl status caddy --no-pager || true)

echo

echo "== caddy unit definition =="
(systemctl cat caddy || true)

echo

echo "== /etc/caddy/Caddyfile (head) =="
(if [ -f /etc/caddy/Caddyfile ]; then
  if command -v sudo >/dev/null 2>&1; then
    (sudo -n sed -n '1,160p' /etc/caddy/Caddyfile) || echo "NO ACCESS: /etc/caddy/Caddyfile (sudo -n failed)"
  else
    (sed -n '1,160p' /etc/caddy/Caddyfile) || echo "NO ACCESS: /etc/caddy/Caddyfile"
  fi
else
  echo "MISSING: /etc/caddy/Caddyfile"
fi)

echo

echo "== caddy validate =="
(if command -v caddy >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    (sudo -n caddy validate --config /etc/caddy/Caddyfile) || echo "VALIDATE FAILED (sudo -n failed or config invalid)"
  else
    caddy validate --config /etc/caddy/Caddyfile || true
  fi
else
  echo "caddy binary not found"
fi)
EOF

echo "[IDC1] caddy probe completed."
