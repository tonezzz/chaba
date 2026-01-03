#!/usr/bin/env sh
set -eu

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
ONE_MCP_BACKEND=${ONE_MCP_BACKEND:-http://127.0.0.1:3050}
GUAC_BACKEND=${GUAC_BACKEND:-http://127.0.0.1:3002}

echo "[IDC1] Ensuring Caddy hub vhost + /guac route on $SSH_HOST as $SSH_USER"

ssh \
  -i "$SSH_KEY_PATH" \
  -p "$SSH_PORT" \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$SSH_USER@$SSH_HOST" \
  ONE_MCP_BACKEND="$ONE_MCP_BACKEND" \
  GUAC_BACKEND="$GUAC_BACKEND" \
  bash -s <<'EOF'
set -euo pipefail

CADDYFILE=/etc/caddy/Caddyfile
TMPDIR=/tmp
TMPFILE="$TMPDIR/Caddyfile.$$"

if ! command -v sudo >/dev/null 2>&1; then
  echo "[REMOTE] sudo not found; cannot proceed" >&2
  exit 2
fi

if ! sudo -n true 2>/dev/null; then
  echo "[REMOTE] sudo -n not permitted for this user; cannot edit/reload Caddy" >&2
  exit 3
fi

if [ ! -f "$CADDYFILE" ]; then
  echo "[REMOTE] Missing $CADDYFILE" >&2
  exit 4
fi

# 1) Ensure /guac handlers exist inside test.idc1.surf-thailand.com block.
if sudo -n grep -q "handle_path /guac/\*" "$CADDYFILE"; then
  echo "[REMOTE] /guac route already present"
else
  echo "[REMOTE] Inserting /guac route into test.idc1.surf-thailand.com"

  sudo -n awk -v GUAC_BACKEND="${GUAC_BACKEND}" '
    BEGIN { in_test=0; injected=0; }
    /^test\.idc1\.surf-thailand\.com[[:space:]]*\{/ { in_test=1 }
    in_test && /^\}/ {
      if (!injected) {
        print "";
        print "    handle /guac {";
        print "        redir * /guac/";
        print "    }";
        print "";
        print "    handle_path /guac/* {";
        print "        reverse_proxy " GUAC_BACKEND;
        print "    }";
        injected=1;
      }
      in_test=0
    }
    { print }
  ' "$CADDYFILE" > "$TMPFILE"

  sudo -n mv "$TMPFILE" "$CADDYFILE"
fi

# 2) Ensure 1mcp.idc1.surf-thailand.com vhost exists.
if sudo -n grep -q "^1mcp\.idc1\.surf-thailand\.com[[:space:]]*{" "$CADDYFILE"; then
  echo "[REMOTE] 1mcp.idc1 vhost already present"
else
  echo "[REMOTE] Appending 1mcp.idc1 vhost"
  sudo -n tee -a "$CADDYFILE" >/dev/null <<VHOST

1mcp.idc1.surf-thailand.com {
    encode gzip zstd

    reverse_proxy ${ONE_MCP_BACKEND}

    log {
        output file /var/log/caddy/1mcp.idc1.access.log
    }
}
VHOST
fi

echo "[REMOTE] Validating Caddy config"
sudo -n caddy validate --config "$CADDYFILE"

echo "[REMOTE] Reloading Caddy"
sudo -n systemctl reload caddy

echo "[REMOTE] Done"
EOF

echo "[IDC1] ensure-hub completed."
