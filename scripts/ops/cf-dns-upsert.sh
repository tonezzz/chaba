#!/usr/bin/env bash
# cf-dns-upsert.sh — idempotent Cloudflare DNS record create/update.
# Written for fleet-installer-v2 (app.surf-thailand.com A record) but generic.
#
# Needs a DNS-capable CF_API_TOKEN (Zone > DNS > Edit on the zone) in
# ~/.config/secrets/cloudflare.env — the cfat_ token died 2026-10-26;
# mint the replacement at dash.cloudflare.com/profile/api-tokens.
#
#   ./cf-dns-upsert.sh                          # app -> 157.85.102.125 (proxied)
#   ./cf-dns-upsert.sh api.surf-thailand.com    # idempotent re-check
#   ./cf-dns-upsert.sh NAME CONTENT [TYPE] [PROXIED]
set -euo pipefail

ENV_FILE="${CLOUDFLARE_ENV:-$HOME/.config/secrets/cloudflare.env}"
CF_API="https://api.cloudflare.com/client/v4"

NAME="${1:-app.surf-thailand.com}"
CONTENT="${2:-157.85.102.125}"           # idc03 caddy-edge public bind
TYPE="${3:-A}"
PROXIED="${4:-true}"                     # same as api.surf-thailand.com

# shellcheck disable=SC1090
source "$ENV_FILE"
: "${CF_API_TOKEN:?CF_API_TOKEN missing in $ENV_FILE}"
: "${CF_API_ACCOUNT_ID:?CF_API_ACCOUNT_ID missing in $ENV_FILE}"

cf() { curl -sf -H "Authorization: Bearer $CF_API_TOKEN" \
       -H "Content-Type: application/json" "$@" ; }

# Preflight: verify the token can read this zone (catches the read-only case)
ZONE_NAME="${NAME#*.}"                    # strip leftmost label -> zone guess
case "$NAME" in
  *.*.*) ZONE_NAME="${NAME#*.}" ;;        # a.b.zone -> b.zone (one label deep)
esac
ZONE=$(cf "$CF_API/zones?name=$ZONE_NAME")
ZONE_ID=$(echo "$ZONE" | python3 -c 'import sys,json
try: print(json.load(sys.stdin)["result"][0]["id"])
except Exception: sys.exit("zone lookup failed — token lacks zone read")')
echo "zone $ZONE_NAME = $ZONE_ID"

EXISTING=$(cf "$CF_API/zones/$ZONE_ID/dns_records?type=$TYPE&name=$NAME" \
  | python3 -c 'import sys,json
r=json.load(sys.stdin)
if not r.get("success"): sys.exit(str(r.get("errors")))
recs=r["result"]
if recs: print(recs[0]["id"] + " " + recs[0]["content"])')

if [ -n "$EXISTING" ]; then
  RID="${EXISTING%% *}"; OLD="${EXISTING#* }"
  if [ "$OLD" = "$CONTENT" ]; then
    echo "record already correct: $TYPE $NAME -> $CONTENT"
    exit 0
  fi
  cf -X PUT "$CF_API/zones/$ZONE_ID/dns_records/$RID" \
    -d "{\"type\":\"$TYPE\",\"name\":\"$NAME\",\"content\":\"$CONTENT\",\"proxied\":$PROXIED}" >/dev/null
  echo "updated: $TYPE $NAME $OLD -> $CONTENT (proxied=$PROXIED)"
else
  cf -X POST "$CF_API/zones/$ZONE_ID/dns_records" \
    -d "{\"type\":\"$TYPE\",\"name\":\"$NAME\",\"content\":\"$CONTENT\",\"proxied\":$PROXIED}" >/dev/null
  echo "created: $TYPE $NAME -> $CONTENT (proxied=$PROXIED)"
fi
