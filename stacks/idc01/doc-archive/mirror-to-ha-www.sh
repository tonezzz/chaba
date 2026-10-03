#!/usr/bin/env bash
# mirror-to-ha-www.sh — publish doc-archive pages to tony-ha www/documents/
# so casted /local/documents/<slug>/<page> URLs actually render on screens
# (the reported A-68 cast failed with a broken image because this tree did
# not exist). Runs on idc01; rsyncs over tailscale ssh to tony-dell.
set -euo pipefail

ENV_FILE="${DOC_ARCHIVE_ENV:-$HOME/.config/secrets/doc-archive.env}"
PORT=$(grep -oP 'DOC_ARCHIVE_PORT=\K.*' "$ENV_FILE")
BIND=$(grep -oP 'DOC_ARCHIVE_BIND=\K.*' "$ENV_FILE")
KEY=$(grep -oP 'API_KEY=\K.*' "$ENV_FILE")
MDDB="${MDDB_BASE:-http://100.74.146.0:11023}"
# tony-dell-m2m = ssh alias → 100.68.142.13:8222 (socket-activated sshd, key
# auth only) — bypasses tailscale-ssh :22 check mode which gates automation on
# periodic browser re-auth. See ssot.learning.idc01-warp-tailscaled.2026-09-24.
TARGET_HOST="${HA_WWW_HOST:-tony-dell-m2m}"
TARGET_DIR="${HA_WWW_DIR:-.config/home-assistant/www/documents}"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

# Bound every curl so an unavailable/hung MDDB or doc-archive cannot stall the
# hourly run forever (TimeoutStartSec in the unit is the outer backstop).
CURL=(curl -sf --connect-timeout 10 --max-time 120)

slugs=$("${CURL[@]}" -X POST "$MDDB/v1/search" -H 'content-type: application/json' \
  -d '{"collection":"documents","query":"","limit":100}' \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
docs = d if isinstance(d, list) else d.get("docs", d.get("results", []))
print(" ".join(x["key"] for x in docs if x.get("key")))')

for slug in $slugs; do
  mkdir -p "$STAGE/$slug"
  # abort the whole run if a manifest fetch fails — continuing with an
  # empty stage + rsync --delete would wipe the mirror (seen 2026-09-30
  # when Drive's oauth token was revoked: every manifest 502'd)
  manifest=$("${CURL[@]}" -H "X-API-Key: $KEY" "http://$BIND:$PORT/v1/archive/$slug") || {
    echo "doc-mirror: manifest fetch failed for $slug — aborting" >&2
    exit 1
  }
  pages=$(printf '%s' "$manifest" | python3 -c 'import json,sys
print(len(json.load(sys.stdin)["manifest"]["pages"]))')
  for n in $(seq 1 "$pages"); do
    name=$(printf '%s' "$manifest" | python3 -c "import json,sys
print(json.load(sys.stdin)['manifest']['pages'][$n-1]['name'])")
    "${CURL[@]}" -H "X-API-Key: $KEY" \
      -o "$STAGE/$slug/$name" "http://$BIND:$PORT/v1/archive/$slug/page/$n"
  done
done

# second guard: never --delete an empty stage onto the target
if [ -z "$(find "$STAGE" -type f -print -quit)" ]; then
  echo "doc-mirror: stage is empty — refusing to rsync --delete" >&2
  exit 1
fi

# --delete: retracted archives disappear from the mirror too. The dir is
# dedicated to this mirror.
rsync -a --delete --timeout=120 \
  -e 'ssh -o ConnectTimeout=10 -o BatchMode=yes' \
  "$STAGE/" "$TARGET_HOST:$TARGET_DIR/"
echo "doc-mirror: synced $(find "$STAGE" -type f | wc -l) pages across $(echo $slugs | wc -w) archives"
