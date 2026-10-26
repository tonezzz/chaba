#!/usr/bin/env bash
# cf-dns-upsert-when-ready.sh — companion to cf-dns-upsert.sh for
# fleet-installer-v2. Fired by cf-dns-upsert.path (systemd.path watching
# ~/.config/secrets/cloudflare.env PathModified).
#
# Behaviour: if CF_API_TOKEN can't read the surf-thailand.com zone yet
# (the dead cfat_ token or a Workers-only replacement), exit quietly and
# stay armed. The moment a DNS-capable token lands, run cf-dns-upsert.sh
# (idempotent A record app.surf-thailand.com -> 157.85.102.125 proxied),
# comment on the card, then disable the watcher.
set -uo pipefail

ENV_FILE="${CLOUDFLARE_ENV:-$HOME/.config/secrets/cloudflare.env}"
REPO="${CHABA_REPO:-$HOME/CascadeProjects/chaba}"
UPSERT="$REPO/scripts/ops/cf-dns-upsert.sh"
CARD="fleet-installer-v2"
BOARD="https://idc03.taila0626a.ts.net:10000"

# shellcheck disable=SC1090
source "$ENV_FILE" 2>/dev/null || exit 0
[ -n "${CF_API_TOKEN:-}" ] || exit 0

# Gate on a real zone read — /user/tokens/verify historically lies for
# scoped tokens (rejects cfat_ while zone APIs worked, per ssot.secrets).
ZONE=$(curl -sf -m 10 \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=surf-thailand.com" 2>/dev/null) || exit 0
echo "$ZONE" | python3 -c 'import sys,json; sys.exit(0 if json.load(sys.stdin).get("result") else 1)' \
  || exit 0

comment() {
  python3 - "$1" "$CARD" "$BOARD" <<'PY'
import json, sys, urllib.request
text, card, board = sys.argv[1:4]
try:
    urllib.request.urlopen(urllib.request.Request(
        board + "/comment",
        data=json.dumps({"id": card, "from": "chaba", "text": text}).encode(),
        headers={"Content-Type": "application/json"}), timeout=10)
except Exception:
    pass
PY
}

if OUT=$("$UPSERT" 2>&1); then
  echo "$OUT"
  comment "cf-dns-upsert ran on $HOSTNAME via the armed watcher: $(echo "$OUT" | tail -1) — app.surf-thailand.com A record -> 157.85.102.125 (proxied). Watcher self-disabled."
  systemctl --user disable --now cf-dns-upsert.path 2>/dev/null || true
else
  echo "$OUT" >&2
  comment "cf-dns-upsert watcher fired on $HOSTNAME but the upsert FAILED: $(echo "$OUT" | head -3 | tr '\n' ' ')"
fi
