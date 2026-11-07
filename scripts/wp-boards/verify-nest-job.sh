#!/usr/bin/env bash
# Post-deploy verification for the chaba-boards nest_job CPT drift repair
# (card repair-wp-nest-job-cpt-drift, 2026-10-26).
#
# Runs from any tailnet host with NO WP creds:
#   1. anonymous WP REST proves the CPT is registered (200 vs 404
#      rest_no_route) — private posts stay invisible either way
#   2. board-api POST /job on idc03 does the authenticated write
#      round-trip: parent create, child create via parent=<slug>,
#      parent update with comms + meta merge
#
# Usage: verify-nest-job.sh [slug-prefix]   (default: drift-probe)
# Exit 0 = all checks passed.
set -euo pipefail

SITE="${WP_SITE:-https://boards.surf-thailand.com/wp}"
BAPI="${BOARD_API:-https://idc03.taila0626a.ts.net:10000}"
P="${1:-drift-probe}-$(date +%Y%m%d%H%M)"
fail=0

say() { printf '%s\n' "$*"; }

say "== 1. /wp/v2/types — CPT registration"
types=$(curl -sS --max-time 20 "$SITE/index.php?rest_route=/wp/v2/types")
for cpt in nest_job activity; do
  if printf '%s' "$types" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if '$cpt' in d else 1)"; then
    say "   $cpt: registered"
  else
    say "   $cpt: MISSING from /wp/v2/types"
    fail=1
  fi
done

say "== 2. anonymous /wp/v2/nest_job — route live, nothing leaked"
code=$(curl -sS -o /tmp/_nj.json -w '%{http_code}' --max-time 15 \
  "$SITE/index.php?rest_route=/wp/v2/nest_job&per_page=5")
body=$(cat /tmp/_nj.json)
say "   HTTP $code  body: ${body:0:120}"
[ "$code" = "200" ] || fail=1
# anonymous must see an empty list (all nest_job posts are private)
if [ "$code" = "200" ]; then
  printf '%s' "$body" | python3 -c "
import json,sys
d = json.load(sys.stdin)
assert d == [], f'anonymous saw {len(d)} posts — private visibility broken!'
" || { say '   FAIL: private posts visible anonymously'; fail=1; }
fi

say "== 3. board-api /job write round-trip ($P-*)"
job() {
  curl -sS --max-time 60 -X POST "$BAPI/job" \
    -H 'Content-Type: application/json' -d "$1"
}

r1=$(job "{\"from\":\"devin\",\"slug\":\"$P-parent\",\
\"title\":\"Drift probe parent\",\"kind\":\"queue\",\"status\":\"queued\",\
\"host\":\"probe\",\"comms\":\"probe parent created by verify-nest-job.sh\"}")
say "   parent create: $r1"
printf '%s' "$r1" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') and d.get('post_id'), d" || fail=1

r2=$(job "{\"from\":\"devin\",\"slug\":\"$P-child\",\
\"title\":\"Drift probe child\",\"kind\":\"sub\",\"status\":\"queued\",\
\"parent\":\"$P-parent\",\"pack\":\"probe-pack\",\"runner\":\"verify-script\",\
\"comms\":\"probe child linked by slug\"}")
say "   child create : $r2"
printf '%s' "$r2" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok'), d" || fail=1

r3=$(job "{\"from\":\"devin\",\"slug\":\"$P-parent\",\"status\":\"done\",\
\"meta\":{\"result_ref\":\"probe://verify-ok\"},\
\"note\":\"probe parent status->done + meta merge\"}")
say "   parent update: $r3"
printf '%s' "$r3" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') and d.get('action')=='updated', d" || fail=1

if [ "$fail" = 0 ]; then
  say "RESULT: PASS — nest_job registered, private, and /job upserts work"
else
  say "RESULT: FAIL — see lines above"
fi
exit "$fail"
