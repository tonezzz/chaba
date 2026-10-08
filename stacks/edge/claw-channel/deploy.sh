#!/usr/bin/env bash
# deploy.sh — idempotent deploy of the claw-channel worker + KV.
# Card: lab-cf-kv-claw-channel. Run from any host holding
# ~/.config/secrets/cloudflare.env (omen copy is current; dell/idc01/
# idc02 carry a stale cfat_ token — see card comms 2026-10-08).
#
#   ./deploy.sh [--env-file PATH] [--host claw.surf-thailand.com]
#
# Token needs: Workers KV Storage Edit, Workers Scripts Edit,
# Workers Routes Edit, Zone DNS Edit (zone surf-thailand.com).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EDGE_DIR="$(cd "$HERE/../../../edge/claw-channel" && pwd)"
ENV_FILE="${CLOUDFLARE_ENV:-$HOME/.config/secrets/cloudflare.env}"
CLAW_ENV="$HOME/.config/secrets/claw-channel.env"
CLAW_HOST="claw.surf-thailand.com"
ZONE_NAME="surf-thailand.com"
NS_NAME="claw-channel"
WRANGLER="npx -y wrangler@4"
CF_API="https://api.cloudflare.com/client/v4"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --host)     CLAW_HOST="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# shellcheck disable=SC1090
source "$ENV_FILE"
: "${CF_API_TOKEN:?CF_API_TOKEN missing in $ENV_FILE}"
: "${CF_API_ACCOUNT_ID:?CF_API_ACCOUNT_ID missing in $ENV_FILE}"
export CLOUDFLARE_API_TOKEN="$CF_API_TOKEN"
export CLOUDFLARE_ACCOUNT_ID="$CF_API_ACCOUNT_ID"

cf() { curl -sf -H "Authorization: Bearer $CF_API_TOKEN" \
       -H "Content-Type: application/json" "$CF_API$1" ${2:+-d "$2"}; }

echo "== preflight =="
curl -s -H "Authorization: Bearer $CF_API_TOKEN" "$CF_API/user/tokens/verify" \
  | grep -q '"status":"active"' || { echo "token not active"; exit 1; }

if ! cf "/accounts/$CF_API_ACCOUNT_ID/storage/kv/namespaces?per_page=1" >/dev/null; then
  cat >&2 <<EOF
Token lacks required scopes. Dashboard:
  dash.cloudflare.com -> profile -> API Tokens -> edit the cfut_ token
  Account: Workers KV Storage  -> Edit
  Account: Workers R2 Storage  -> Edit   (optional, report artifacts)
  Zone surf-thailand.com: Workers Routes -> Edit
  Zone surf-thailand.com: DNS            -> Edit
EOF
  exit 1
fi

ZONE_ID=$(curl -sf -H "Authorization: Bearer $CF_API_TOKEN" \
  "$CF_API/zones?name=$ZONE_NAME" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"][0]["id"])')
echo "zone $ZONE_NAME = $ZONE_ID"

echo "== KV namespace =="
NS_ID=$(cd "$EDGE_DIR" && $WRANGLER kv namespace list 2>/dev/null \
  | python3 -c 'import sys,json
ns=[n for n in json.load(sys.stdin) if n["title"]=="'"$NS_NAME"'"]
print(ns[0]["id"] if ns else "")')
if [[ -z "$NS_ID" ]]; then
  NS_ID=$(cd "$EDGE_DIR" && $WRANGLER kv namespace create "$NS_NAME" \
    | grep -o '"id": *"[a-f0-9]*"' | grep -o '[a-f0-9]\{32\}')
fi
echo "namespace $NS_NAME = $NS_ID"

echo "== render deploy config =="
DEPLOY_TOML="$EDGE_DIR/wrangler.deploy.toml"
sed "s/REPLACE_WITH_CLAW_KV_NAMESPACE_ID/$NS_ID/;
     s|edge.surf-thailand.com/claw/\*|$CLAW_HOST/*|" \
    "$EDGE_DIR/wrangler.toml" > "$DEPLOY_TOML"

echo "== ingest secret =="
mkdir -p "$(dirname "$CLAW_ENV")"
if ! grep -q '^CLAW_INGEST_KEY=' "$CLAW_ENV" 2>/dev/null; then
  (umask 077; echo "CLAW_INGEST_KEY=$(openssl rand -hex 24)" >> "$CLAW_ENV")
  echo "generated CLAW_INGEST_KEY -> $CLAW_ENV"
fi
CLAW_INGEST_KEY=$(grep '^CLAW_INGEST_KEY=' "$CLAW_ENV" | cut -d= -f2-)
(cd "$EDGE_DIR" && printf '%s' "$CLAW_INGEST_KEY" \
  | $WRANGLER secret put INGEST_KEY --config "$DEPLOY_TOML")

echo "== DNS (AAAA $CLAW_HOST -> 100::, proxied) =="
NAME="${CLAW_HOST%.${ZONE_NAME}}"
EXIST=$(curl -sf -H "Authorization: Bearer $CF_API_TOKEN" \
  "$CF_API/zones/$ZONE_ID/dns_records?name=$CLAW_HOST" \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["result"]))')
if [[ "$EXIST" == "0" ]]; then
  cf "/zones/$ZONE_ID/dns_records" \
    "{\"type\":\"AAAA\",\"name\":\"$NAME\",\"content\":\"100::\",\"proxied\":true}" >/dev/null
  echo "created AAAA $CLAW_HOST"
else
  echo "DNS record exists"
fi

echo "== deploy worker + route ($CLAW_HOST/*) =="
(cd "$EDGE_DIR" && $WRANGLER deploy --config "$DEPLOY_TOML")

echo "== seed demo command so anonymous GET has content =="
cf "/accounts/$CF_API_ACCOUNT_ID/storage/kv/namespaces/$NS_ID/values/cmd:demo" \
  '{"cmd":"noop","note":"seeded by deploy.sh","at":"'"$(date -u +%FT%TZ)"'"}' >/dev/null

echo "== verify =="
echo "GET  https://$CLAW_HOST/demo            -> $(curl -s -o /dev/null -w '%{http_code}' "https://$CLAW_HOST/demo")"
echo "GET  https://$CLAW_HOST/digest/board    -> $(curl -s -o /dev/null -w '%{http_code}' "https://$CLAW_HOST/digest/board")"
echo "POST bad key (expect 403)               -> $(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'X-Ingest-Key: wrong' -H 'Content-Type: application/json' -d '{}' "https://$CLAW_HOST/report/selftest")"
echo "POST good key (expect 200)              -> $(curl -s -o /dev/null -w '%{http_code}' -X POST -H "X-Ingest-Key: $CLAW_INGEST_KEY" -H 'Content-Type: application/json' -d '{"selftest":true}' "https://$CLAW_HOST/report/selftest")"
echo "GET  https://$CLAW_HOST/report/selftest -> $(curl -s -o /dev/null -w '%{http_code}' "https://$CLAW_HOST/report/selftest")"
echo "done — publish the board digest with:  python3 scripts/claw-publish.py"
