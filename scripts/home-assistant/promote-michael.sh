#!/usr/bin/env bash
# Promote the forked sunsynk-power-flow-card bundle + selected tony-test
# dashboard views from michael-dev to michael-ha, in one verified step.
#
# DEV-FIRST RULE: only run this when work on michael-dev is finished and the
# user has explicitly approved promotion.
#
# Usage:
#   promote-michael.sh [--dry-run] [--views tpl,pfg2|all] [--cleanup] [--rollback]
#
# What it does (in order):
#   1. Preflight   - ha token, REST 200, ssh reachability, dev bundle present
#   2. Bundle      - scp the *dev-deployed* bundle file to michael-ha /local
#   3. Resource    - bump michael-ha lovelace resource url via websocket
#   4. Views       - merge dev's selected views into michael-ha tony-test
#                    (websocket, by path - ha-only views are preserved)
#   5. Verify      - bundle HTTP 200 on michael-ha + resource list contains it
#   6. Cleanup     - optional: delete stale fork bundles not referenced
#   7. Rollback    - optional: flip resource url back to the previous bundle
#
# Auth:
#   michael-ha REST/ws token: ~/.local/share/home-assistant-michael/ha-token
#   michael-ha SSH key:       ~/.ssh/michael-ha
#   michael-dev token:        ~/.config/secrets/ha-michael-dev.env (HASS_TOKEN)
set -euo pipefail

CARD_REPO="${CARD_REPO:-/home/tony/CascadeProjects/sunsynk-power-flow-card}"

DEV_HOST="${DEV_HOST:-tony-dell}"
DEV_WWW="/home/tony/.config/michael-dev/www"
DEV_RES="/home/tony/.config/michael-dev/.storage/lovelace_resources"
DEV_URL="${DEV_URL:-https://tony-dell.taila0626a.ts.net:8124}"

HA_HOST="${MICHAEL_REMOTE_HOST:-michael-ha}"
HA_URL="${HA_URL:-http://michael-ha:8123}"
HA_WWW="/config/www"
HA_SSH_KEY="${MICHAEL_SSH_KEY:-$HOME/.ssh/michael-ha}"
HA_TOKEN_FILE="${MICHAEL_HA_TOKEN:-$HOME/.local/share/home-assistant-michael/ha-token}"

BASE="sunsynk-power-flow-card-fork"
DASH="tony-test"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

DRY_RUN=0
CLEANUP=0
ROLLBACK=0
VIEWS="tpl"

usage() { sed -n '2,25p' "$0"; exit 0; }
log() { echo "[promote] $*"; }
die() { echo "[promote] ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
	case "$1" in
	-n | --dry-run) DRY_RUN=1 ;;
	--cleanup) CLEANUP=1 ;;
	--rollback) ROLLBACK=1 ;;
	--views) VIEWS="$2"; shift ;;
	-h | --help) usage ;;
	*) die "unknown arg: $1" ;;
	esac
	shift
done

SSH="ssh -o ConnectTimeout=5 -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -i $HA_SSH_KEY"
SCP="scp -o ConnectTimeout=5 -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -i $HA_SSH_KEY"

# ---------- preflight ----------
[ -f "$HA_TOKEN_FILE" ] || die "ha token missing: $HA_TOKEN_FILE"
HA_TOKEN=$(cat "$HA_TOKEN_FILE")
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/config")
[ "$code" = "200" ] || die "michael-ha REST returned $code"
$SSH "$HA_HOST" true 2>/dev/null || die "ssh $HA_HOST failed"
[ -f ~/.config/secrets/ha-michael-dev.env ] || die "missing dev token env"
# shellcheck disable=SC1091
source ~/.config/secrets/ha-michael-dev.env
[ -n "${HASS_TOKEN:-}" ] || die "HASS_TOKEN empty in dev token env"

cur_ha=$($SSH "$HA_HOST" "grep -o '${BASE}-v[0-9]*' /config/.storage/lovelace_resources | head -1 | grep -o '[0-9]*$'" || true)
cur_dev=$(ssh "$DEV_HOST" "grep -o '${BASE}-v[0-9]*' '$DEV_RES' | head -1 | grep -o '[0-9]*$'")
[ -n "$cur_dev" ] || die "no ${BASE}-vN resource on michael-dev"
file="${BASE}-v${cur_dev}.js"
log "michael-dev: v$cur_dev   michael-ha: v${cur_ha:-none}"

# dist staleness guard (warn only; the promoted artifact is the dev-deployed file)
if [ -f "$CARD_REPO/dist/sunsynk-power-flow-card.js" ]; then
	h_dist=$(sha256sum "$CARD_REPO/dist/sunsynk-power-flow-card.js" | cut -d' ' -f1)
	h_dev=$(ssh "$DEV_HOST" "sha256sum '$DEV_WWW/$file'" | cut -d' ' -f1)
	[ "$h_dist" = "$h_dev" ] || log "WARN: local dist/ != dev-deployed $file (dist may be stale; promoting the live dev artifact)"
fi

if [ "$ROLLBACK" -eq 1 ]; then
	[ -n "$cur_ha" ] || die "nothing to roll back to"
	prev=$($SSH "$HA_HOST" "ls /config/www/${BASE}-v*.js | sed 's/.*-v//;s/\.js//' | sort -n | awk -v c=$cur_ha '\$1<c' | tail -1")
	[ -n "$prev" ] || die "no older bundle on michael-ha to roll back to"
	rollback_file="${BASE}-v${prev}.js"
	log "rollback: resource -> /local/$rollback_file"
	[ "$DRY_RUN" -eq 1 ] && exit 0
	HASS_TOKEN="$HA_TOKEN" python3 "$SCRIPT_DIR/ws-resource-url.py" "$HA_URL" "$BASE" "$rollback_file"
	log "rolled back to v$prev (bundle file kept on ha www)"
	exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
	log "DRY RUN: would deploy $file, bump resource, merge views: $VIEWS"
	$SSH "$HA_HOST" "ls /config/www/${BASE}-v*.js 2>/dev/null"
	exit 0
fi

# ---------- deploy bundle (the exact file live on michael-dev) ----------
log "copying $file dev -> michael-ha"
scp "$DEV_HOST:$DEV_WWW/$file" /tmp/"$file"
$SCP /tmp/"$file" "$HA_HOST:$HA_WWW/$file"
rm -f /tmp/"$file"

# ---------- bump lovelace resource ----------
log "updating michael-ha lovelace resource -> /local/$file"
HASS_TOKEN="$HA_TOKEN" python3 "$SCRIPT_DIR/ws-resource-url.py" "$HA_URL" "$BASE" "$file"

# ---------- merge dashboard views ----------
log "merging views [$VIEWS] into michael-ha $DASH"
HASS_TOKEN="$HASS_TOKEN" python3 - "$DEV_URL" "$DASH" "$VIEWS" <<'PY' > /tmp/promote-views.json
import asyncio, json, os, sys
import websockets

async def main():
	url, path, want = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
	ws_url = url.replace('http', 'ws', 1) + '/api/websocket'
	async with websockets.connect(ws_url) as ws:
		async def cmd(p):
			cmd.i = getattr(cmd, 'i', 1) + 1
			p['id'] = cmd.i
			await ws.send(json.dumps(p))
			while True:
				r = json.loads(await ws.recv())
				if r.get('id') == cmd.i:
					return r
		await ws.recv()
		await ws.send(json.dumps({'type': 'auth', 'access_token': os.environ['HASS_TOKEN']}))
		assert (await ws.recv()).find('auth_ok') != -1
		cfg = await cmd({'type': 'lovelace/config', 'url_path': path})
		assert cfg.get('success'), cfg
		views = cfg['result']['views']
		if want == ['all']:
			sel = views
		else:
			sel = [v for v in views if v.get('path') in want]
		missing = set(want) - {v.get('path') for v in sel}
		assert not missing or want == ['all'], f'dev views not found: {missing}'
		print(json.dumps(sel))

asyncio.run(main())
PY

cat > /tmp/promote-mutate.py <<'PY'
import json
new_views = json.load(open('/tmp/promote-views.json'))
def mutate(config):
	by = {v.get('path'): v for v in config['views']}
	for v in new_views:
		p = v.get('path')
		if p in by:
			config['views'][config['views'].index(by[p])] = v
		else:
			config['views'].append(v)
PY
HASS_TOKEN="$HA_TOKEN" python3 "$SCRIPT_DIR/push-dashboard.py" "$HA_URL" "$DASH" --mutate /tmp/promote-mutate.py
log "views merged: $VIEWS"

# ---------- verify ----------
sleep 3
code=$(curl -s -o /dev/null -w '%{http_code}' "$HA_URL/local/$file")
[ "$code" = "200" ] || die "bundle not served on michael-ha (http $code)"
res=$($SSH "$HA_HOST" "grep -o '${BASE}-v[0-9]*' /config/.storage/lovelace_resources | head -1")
[ "$res" = "${BASE}-v${cur_dev}" ] || die "resource still points at $res"
log "verified: michael-ha now serves /local/$file"

# ---------- optional cleanup of stale bundles ----------
if [ "$CLEANUP" -eq 1 ]; then
	keep1="v$cur_dev"; keep2="v${cur_ha:-0}"
	log "cleanup: keeping $keep1 (current) + $keep2 (previous, rollback)"
	$SSH "$HA_HOST" "cd /config/www && for f in ${BASE}-v*.js; do
		case \"\$f\" in ${BASE}-${keep1}.js|${BASE}-${keep2}.js) : ;; *) rm -f \"\$f\" && echo \"  removed \$f\" ;; esac
	done"
fi

log "done: michael-ha on v$cur_dev — verify PFG2 + TPL visually before closing"
log "reminder: record promotion in SSOT (cards.yml bundle_version, promoted_at)"
