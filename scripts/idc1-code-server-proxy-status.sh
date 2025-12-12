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

CADDYFILE_PATH=${CADDYFILE_PATH:-/etc/caddy/Caddyfile}
TARGET_HOST_PORT=${TARGET_HOST_PORT:-18080}

echo "[IDC1] Inspecting code.idc1.surf-thailand.com proxy backend in $CADDYFILE_PATH on $SSH_HOST as $SSH_USER"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" \
  "CADDYFILE_PATH=\"$CADDYFILE_PATH\" TARGET_HOST_PORT=\"$TARGET_HOST_PORT\" bash -s" <<'EOF'
set -euo pipefail

if ! sudo -n true 2>/dev/null; then
  echo "[REMOTE] sudo is required to read $CADDYFILE_PATH but passwordless sudo is not enabled for this user." >&2
  echo "[REMOTE] Fix: grant NOPASSWD for reading /etc/caddy/Caddyfile (and for reload when switching), or run this manually on the host." >&2
  exit 1
fi

block_start_line=$(sudo -n grep -n '^code\.idc1\.surf-thailand\.com\s*{' "$CADDYFILE_PATH" | head -n1 | cut -d: -f1 || true)
if [[ -z "${block_start_line:-}" ]]; then
  echo "[REMOTE] code.idc1.surf-thailand.com block not found in $CADDYFILE_PATH" >&2
  exit 1
fi

reverse_line=$(sudo -n sed -n "${block_start_line},/^}/p" "$CADDYFILE_PATH" | grep -n 'reverse_proxy' | head -n1 || true)
if [[ -z "${reverse_line:-}" ]]; then
  echo "[REMOTE] reverse_proxy line not found inside code.idc1.surf-thailand.com block" >&2
  exit 1
fi

# reverse_line is like: "42:    reverse_proxy 127.0.0.1:8080"
backend_port=$(sudo -n sed -n "${block_start_line},/^}/p" "$CADDYFILE_PATH" | awk '/reverse_proxy/ {print $2; exit}')
if [[ -z "${backend_port:-}" ]]; then
  echo "[REMOTE] Failed to parse backend from reverse_proxy line" >&2
  exit 1
fi

echo "[REMOTE] reverse_proxy: $backend_port"

case "$backend_port" in
  *:8080)
    echo "[REMOTE] Current backend: $backend_port (legacy code-server)" ;;
  *:18080)
    echo "[REMOTE] Current backend: $backend_port (idc1-stack code-server)" ;;
  *)
    echo "[REMOTE] Current backend: $backend_port (UNKNOWN mapping)" ;;
esac
EOF

echo "[IDC1] Proxy status check completed."
