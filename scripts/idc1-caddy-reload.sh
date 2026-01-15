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

if command -v sudo >/dev/null 2>&1; then
  sudo -n systemctl reload caddy
else
  systemctl reload caddy
fi

echo "[REMOTE] caddy reloaded"
EOF

echo "[IDC1] caddy reload completed."
