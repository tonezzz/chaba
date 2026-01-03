#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER:?Set SSH_USER}"
: "${SSH_HOST:?Set SSH_HOST}"
: "${SSH_KEY_PATH:?Set SSH_KEY_PATH}"

SSH_PORT=${SSH_PORT:-22}
IDC1_STACK_DIR=${IDC1_STACK_DIR:-/home/chaba/chaba/stacks/idc1-stack}

COREFILE_REL=${COREFILE_REL:-config/coredns/Corefile}
CADDYFILE_REL=${CADDYFILE_REL:-config/caddy/Caddyfile}

# NOTE: idc1 no longer uses mcp0. This script only keeps VPN DNS + Caddy config in sync.

SSH_KEY_EFFECTIVE_PATH="$SSH_KEY_PATH"
SSH_KEY_TMP=""
if [ -f "$SSH_KEY_PATH" ]; then
  SSH_KEY_TMP="$(mktemp)"
  cp "$SSH_KEY_PATH" "$SSH_KEY_TMP"
  chmod 600 "$SSH_KEY_TMP" || true
  SSH_KEY_EFFECTIVE_PATH="$SSH_KEY_TMP"
fi

cleanup() {
  if [ -n "${SSH_KEY_TMP:-}" ] && [ -f "${SSH_KEY_TMP:-}" ]; then
    rm -f "$SSH_KEY_TMP" || true
  fi
}
trap cleanup EXIT

SSH_COMMON_OPTS=(
  -i "$SSH_KEY_EFFECTIVE_PATH"
  -p "$SSH_PORT"
  -o IdentitiesOnly=yes
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

echo "[IDC1] Applying idc1 VPN DNS + Caddy config sync on $SSH_HOST"

ssh "${SSH_COMMON_OPTS[@]}" "$SSH_USER@$SSH_HOST" \
  "IDC1_STACK_DIR=$IDC1_STACK_DIR COREFILE_REL=$COREFILE_REL CADDYFILE_REL=$CADDYFILE_REL bash -s" <<'EOF'
set -euo pipefail

IDC1_STACK_DIR=${IDC1_STACK_DIR:?}
COREFILE_PATH="$IDC1_STACK_DIR/${COREFILE_REL:?}"
CADDYFILE_PATH="$IDC1_STACK_DIR/${CADDYFILE_REL:?}"

if [ ! -f "$COREFILE_PATH" ]; then
  echo "[REMOTE] Corefile not found: $COREFILE_PATH" >&2
  exit 2
fi
if [ ! -f "$CADDYFILE_PATH" ]; then
  echo "[REMOTE] Caddyfile not found: $CADDYFILE_PATH" >&2
  exit 2
fi

echo "[REMOTE] Patching CoreDNS Corefile: $COREFILE_PATH"
COREFILE_TMP="$(mktemp)"
COREFILE_PATH="$COREFILE_PATH" COREFILE_TMP="$COREFILE_TMP" python3 - <<'PY'
import os
from pathlib import Path

corefile_path = Path(os.environ['COREFILE_PATH'])
corefile_tmp = Path(os.environ['COREFILE_TMP'])
text = corefile_path.read_text(encoding='utf-8')
lines = text.splitlines(True)

def find_block(start_pred):
  start = None
  for i, line in enumerate(lines):
    if start_pred(line):
      start = i
      break
  if start is None:
    return None

  depth = 0
  end = None
  for j in range(start, len(lines)):
    depth += lines[j].count('{')
    depth -= lines[j].count('}')
    if j > start and depth == 0:
      end = j
      break
  if end is None:
    return None
  return start, end

vpn_block = find_block(lambda l: l.lstrip().startswith('vpn:53') and '{' in l)
if vpn_block is None:
  raise SystemExit('vpn:53 block not found in Corefile')

start, end = vpn_block
block = lines[start:end+1]

rewrite_lines = [l for l in block if l.lstrip().startswith('rewrite name regex')]

hosts_idx = None
for i, l in enumerate(block):
  if l.lstrip().startswith('hosts') and '{' in l:
    hosts_idx = i
    break
if hosts_idx is None:
  raise SystemExit('hosts block not found in vpn:53 block')

# find hosts block end within vpn block
depth = 0
hosts_end = None
for j in range(hosts_idx, len(block)):
  depth += block[j].count('{')
  depth -= block[j].count('}')
  if j > hosts_idx and depth == 0:
    hosts_end = j
    break
if hosts_end is None:
  raise SystemExit('hosts block not closed')

hosts_block = block[hosts_idx:hosts_end+1]

# remove original hosts block and rewrite lines from vpn block
filtered = []
skip = set(range(hosts_idx, hosts_end+1))
for i, l in enumerate(block):
  if i in skip:
    continue
  if l.lstrip().startswith('rewrite name regex'):
    continue
  filtered.append(l)

# place hosts before rewrite lines (right after opening line)
open_line = filtered[0]
rest = filtered[1:]

new_block = [open_line]
new_block.extend(hosts_block)
new_block.extend(rewrite_lines)
new_block.extend(rest)

# write back
new_lines = lines[:start] + new_block + lines[end+1:]
new_text = ''.join(new_lines)
if new_text != text:
  corefile_tmp.write_text(new_text, encoding='utf-8')
  print('[REMOTE] Corefile staged in tmp for install.')
else:
  corefile_tmp.write_text(text, encoding='utf-8')
  print('[REMOTE] Corefile already up to date.')
PY

if ! sudo -n test -f "${COREFILE_PATH}.bak"; then
  sudo -n cp -a "$COREFILE_PATH" "${COREFILE_PATH}.bak"
fi

if ! cmp -s "$COREFILE_TMP" "$COREFILE_PATH"; then
  sudo -n install -m 644 "$COREFILE_TMP" "$COREFILE_PATH"
  echo "[REMOTE] Corefile updated."
else
  echo "[REMOTE] Corefile already up to date."
fi

rm -f "$COREFILE_TMP" || true

echo "[REMOTE] Patching Caddyfile: $CADDYFILE_PATH"
CADDYFILE_TMP="$(mktemp)"
CADDYFILE_PATH="$CADDYFILE_PATH" CADDYFILE_TMP="$CADDYFILE_TMP" python3 - <<'PY'
import os
from pathlib import Path

caddyfile_path = Path(os.environ['CADDYFILE_PATH'])
caddyfile_tmp = Path(os.environ['CADDYFILE_TMP'])
text = caddyfile_path.read_text(encoding='utf-8')

# No-op: keep stack Caddyfile as the source of truth.
caddyfile_tmp.write_text(text, encoding='utf-8')
print('[REMOTE] Caddyfile staged in tmp for install.')
PY

if ! sudo -n test -f "${CADDYFILE_PATH}.bak"; then
  sudo -n cp -a "$CADDYFILE_PATH" "${CADDYFILE_PATH}.bak"
fi

if ! cmp -s "$CADDYFILE_TMP" "$CADDYFILE_PATH"; then
  sudo -n install -m 644 "$CADDYFILE_TMP" "$CADDYFILE_PATH"
  echo "[REMOTE] Caddyfile updated."
else
  echo "[REMOTE] Caddyfile already up to date."
fi

rm -f "$CADDYFILE_TMP" || true

echo "[REMOTE] Ensuring /etc/caddy/Caddyfile is updated from stack config"
sudo -n install -m 644 "$CADDYFILE_PATH" /etc/caddy/Caddyfile

echo "[REMOTE] Restarting wg-dns (CoreDNS)"
cd "$IDC1_STACK_DIR"
sudo -n docker compose --profile vpn up -d --force-recreate wg-dns

echo "[REMOTE] Updating /etc/caddy/Caddyfile from stack config"
sudo -n install -m 644 "$CADDYFILE_PATH" /etc/caddy/Caddyfile

echo "[REMOTE] Validating and reloading Caddy"
sudo -n caddy validate --config /etc/caddy/Caddyfile
if sudo -n systemctl is-active --quiet caddy; then
  sudo -n systemctl reload caddy
else
  # Caddy is often running outside systemd on this host.
  # If it's already bound to ports, prefer `caddy reload` (admin API) instead of trying to start another instance.
  if sudo -n ss -ltnp | grep -Eq ':(80|443)\b.*\("caddy",'; then
    sudo -n caddy reload --config /etc/caddy/Caddyfile || true
  else
    sudo -n systemctl start caddy || sudo -n systemctl restart caddy || true
  fi

  # Verify we have a running Caddy either way
  if ! sudo -n ss -ltnp | grep -Eq ':(80|443)\b.*\("caddy",'; then
    echo "[REMOTE] Caddy is not listening on :80/:443 after reload/start attempts." >&2
    echo "[REMOTE] systemctl status caddy.service:" >&2
    sudo -n systemctl status caddy.service --no-pager >&2 || true
    echo "[REMOTE] journalctl -u caddy.service (last 200 lines):" >&2
    sudo -n journalctl -u caddy.service -n 200 --no-pager >&2 || true
    echo "[REMOTE] Listening ports (80/443/2019/8355):" >&2
    sudo -n ss -ltnp | egrep ':(80|443|2019|8355)\b' >&2 || true
    exit 3
  fi
fi

echo "[REMOTE] Completed idc1 VPN DNS + Caddy config sync."
EOF

echo "[IDC1] Done."
