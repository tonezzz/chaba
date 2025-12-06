#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
REMOTE_TEST_URL="${REMOTE_TEST_URL:-https://a1.idc1.surf-thailand.com/test}"

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

echo "[DIAG] Gathering diagnostics from $SSH_HOST as $SSH_USER"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" <<'EOF'
set -euo pipefail
echo "[REMOTE] Hostname: $(hostname)"
echo "[REMOTE] Uptime:"
uptime || true
echo
echo "[REMOTE] Disk usage (top 10 entries):"
df -h | head -n 10 || true
echo
echo "[REMOTE] Recent releases for a1-idc1:"
ls -al /www/a1.idc-1.surf-thailand.com/a1-idc1/releases 2>/dev/null | head -n 20 || true
echo
echo "[REMOTE] Current symlink:"
ls -al /www/a1.idc-1.surf-thailand.com/a1-idc1/current 2>/dev/null || true
echo
echo "[REMOTE] Node processes:"
ps -eo pid,ppid,cmd --sort=-pcpu | grep -i node || true
EOF

echo "[DIAG] Remote diagnostics complete."

echo "[DIAG] Testing public endpoint: $REMOTE_TEST_URL"
if curl -fsSL -w "\nHTTP_STATUS:%{http_code}\n" "$REMOTE_TEST_URL"; then
  echo "[DIAG] Public endpoint reached successfully."
else
  echo "[DIAG] Warning: Unable to reach public endpoint."
fi
