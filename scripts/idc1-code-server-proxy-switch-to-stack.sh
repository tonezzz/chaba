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
LEGACY_PORT=${LEGACY_PORT:-8080}
STACK_PORT=${STACK_PORT:-18080}

echo "[IDC1] Switching code.idc1.surf-thailand.com proxy backend to 127.0.0.1:$STACK_PORT in $CADDYFILE_PATH on $SSH_HOST as $SSH_USER"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" \
  "CADDYFILE_PATH=\"$CADDYFILE_PATH\" LEGACY_PORT=\"$LEGACY_PORT\" STACK_PORT=\"$STACK_PORT\" bash -s" <<'EOF'
set -euo pipefail

if ! sudo -n true 2>/dev/null; then
  echo "[REMOTE] sudo is required to modify $CADDYFILE_PATH and reload caddy, but passwordless sudo is not enabled for this user." >&2
  echo "[REMOTE] Refusing to proceed because this would hang waiting for a password." >&2
  exit 1
fi

backup_path="${CADDYFILE_PATH}.bak-$(date +%Y%m%d%H%M%S)"
sudo -n cp "$CADDYFILE_PATH" "$backup_path"
echo "[REMOTE] Backed up Caddyfile to $backup_path"

block_start_line=$(sudo -n grep -n '^code\.idc1\.surf-thailand\.com\s*{' "$CADDYFILE_PATH" | head -n1 | cut -d: -f1 || true)
if [[ -z "${block_start_line:-}" ]]; then
  echo "[REMOTE] code.idc1.surf-thailand.com block not found in $CADDYFILE_PATH" >&2
  exit 1
fi

current_backend=$(sudo -n sed -n "${block_start_line},/^}/p" "$CADDYFILE_PATH" | awk '/reverse_proxy/ {print $2; exit}')
if [[ -z "${current_backend:-}" ]]; then
  echo "[REMOTE] reverse_proxy line not found inside code.idc1.surf-thailand.com block" >&2
  exit 1
fi

echo "[REMOTE] Existing backend: $current_backend"

if [[ "$current_backend" == "127.0.0.1:${STACK_PORT}" ]]; then
  echo "[REMOTE] Already pointing at stack backend 127.0.0.1:${STACK_PORT}; no change needed."
else
  tmp_path="/tmp/Caddyfile.$$.tmp"

  sudo -n awk -v STACK_PORT="$STACK_PORT" '
    BEGIN { inblock = 0 }
    /^code\.idc1\.surf-thailand\.com[[:space:]]*\{/ { inblock = 1; print; next }
    inblock && /^[[:space:]]*reverse_proxy[[:space:]]+/ {
      print "    reverse_proxy 127.0.0.1:" STACK_PORT
      next
    }
    inblock && /^}/ { inblock = 0; print; next }
    { print }
  ' "$CADDYFILE_PATH" > "$tmp_path"

  sudo -n cp "$tmp_path" "$CADDYFILE_PATH"
  sudo -n rm -f "$tmp_path"

  echo "[REMOTE] Updated reverse_proxy line to 127.0.0.1:${STACK_PORT} inside code.idc1.surf-thailand.com block"
fi

new_backend=$(sudo -n sed -n "${block_start_line},/^}/p" "$CADDYFILE_PATH" | awk '/reverse_proxy/ {print $2; exit}')
echo "[REMOTE] New backend: ${new_backend:-<unknown>}"

echo "[REMOTE] Reloading caddy"
sudo -n systemctl reload caddy

echo "[REMOTE] Verifying via curl https://code.idc1.surf-thailand.com (HTTP status only)"
if command -v curl >/dev/null 2>&1; then
  curl -k -o /dev/null -s -w "HTTP_STATUS:%{http_code}\n" https://code.idc1.surf-thailand.com || true
else
  echo "[REMOTE] curl not available; skipping HTTP verification"
fi
EOF

echo "[IDC1] Proxy switch to stack code-server requested."
