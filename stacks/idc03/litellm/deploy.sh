#!/usr/bin/env bash
# deploy.sh — install the LiteLLM gateway stack on idc03.
# Idempotent. Secrets env is generated once on the host, never committed.
# Usage: ./deploy.sh            (runs over ssh from any tailnet host)
#        ./deploy.sh --local    (run on idc03 itself)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FILES=(litellm-db.container litellm.container litellm-ledger.service litellm-ledger.timer)

if [ "${1:-}" = "--local" ]; then
  for f in "${FILES[@]}"; do
    install -m 644 "$HERE/$f" "$HOME/.config/containers/systemd/$f"
  done
  install -Dm 644 "$HERE/config.yaml" "$HOME/.config/litellm/config.yaml"
else
  ssh -o BatchMode=yes idc03 'mkdir -p ~/.config/containers/systemd ~/.config/litellm'
  for f in "${FILES[@]}"; do
    scp -q "$HERE/$f" "idc03:.config/containers/systemd/$f"
  done
  scp -q "$HERE/config.yaml" "idc03:.config/litellm/config.yaml"
fi

if [ "${1:-}" = "--local" ]; then SHELL_CMD="bash -s"; else SHELL_CMD="ssh -o BatchMode=yes idc03 bash -s"; fi
$SHELL_CMD <<'REMOTE'
set -euo pipefail
ENVF="$HOME/.config/secrets/litellm.env"
if [ ! -f "$ENVF" ]; then
  pgpass="$(openssl rand -hex 24)"
  {
    echo "POSTGRES_USER=litellm"
    echo "POSTGRES_DB=litellm"
    echo "POSTGRES_PASSWORD=$pgpass"
    echo "DATABASE_URL=postgresql://litellm:$pgpass@127.0.0.1:5432/litellm"
    echo "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 24)"
    echo "LITELLM_SALT_KEY=sk-$(openssl rand -hex 24)"
    echo "LITELLM_UI_USERNAME=admin"
    echo "LITELLM_UI_PASSWORD=$(openssl rand -hex 12)"
  } > "$ENVF"
  chmod 600 "$ENVF"
  echo "created $ENVF"
fi
systemctl --user daemon-reload
# quadlet units are generated — [Install] WantedBy already persists them; just start
systemctl --user restart litellm-db.service
systemctl --user restart litellm.service
REMOTE

echo "→ waiting for litellm health…"
for i in $(seq 1 30); do
  if curl -sf -m 3 http://100.102.134.91:4000/health/liveliness -o /dev/null; then
    echo "✓ litellm live at http://100.102.134.91:4000"
    exit 0
  fi
  sleep 4
done
echo "!! not healthy yet — check: ssh idc03 'journalctl --user -u litellm -n 50'" >&2
exit 1
