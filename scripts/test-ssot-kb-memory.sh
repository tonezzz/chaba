#!/bin/bash
# test-ssot-kb-memory.sh — tiered drift/failure checks for SSOT, KB, and memory systems.
#
# Usage:
#   bash scripts/test-ssot-kb-memory.sh          # T0 only (free, no auth/network)
#   bash scripts/test-ssot-kb-memory.sh t1       # T0 + T1 (needs nlm auth + services)
#   bash scripts/test-ssot-kb-memory.sh t1-only  # T1 only
#
# Expected state is declared in docs/ssot/infrastructure/ssot.test-manifest.yml.
# When live state legitimately changes, update the manifest — not this script.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"
MANIFEST="$REPO_ROOT/docs/ssot/infrastructure/ssot.test-manifest.yml"

TIER="${1:-t0}"
PASS=0; FAIL=0; DRIFT=0; SKIP=0

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

ok()    { echo -e "${GREEN}✅ PASS${NC}: $1"; PASS=$((PASS+1)); }
bad()   { echo -e "${RED}❌ FAIL${NC}: $1"; FAIL=$((FAIL+1)); }
drift() { echo -e "${YELLOW}⚠️  DRIFT${NC}: $1"; DRIFT=$((DRIFT+1)); }
skip()  { echo -e "${BLUE}⏭️  SKIP${NC}: $1"; SKIP=$((SKIP+1)); }
hdr()   { echo -e "\n${BLUE}=== $1 ===${NC}"; }

# Read a scalar from the manifest via python (tolerates nested paths like a.b.c)
mget() {
  python3 - "$MANIFEST" "$1" <<'PYEOF'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
cur = doc
for part in sys.argv[2].split('.'):
    if isinstance(cur, dict) and part in cur:
        cur = cur[part]
    else:
        sys.exit(1)
print(cur if not isinstance(cur, (dict, list)) else '')
PYEOF
}

# Host scoping: each system declares `host` in the manifest — `any` runs
# everywhere, a hostname runs only there. This is how the canonical mn01
# runner skips tony-omen-local checks (sessions.db, session-memory, backups).
HOST=$(hostname -s)
host_ok() {
  local h
  h=$(mget "systems.$1.host" 2>/dev/null || true)
  [ -z "$h" ] && h="any"
  [ "$h" = "any" ] || [ "$h" = "$HOST" ]
}

if [ "$TIER" != "t1-only" ]; then

hdr "T0 — SSOT YAML integrity"
if node scripts/ssot-validate-all.mjs >/dev/null 2>&1; then
  ok "ssot-validate-all.mjs — all SSOT files valid"
else
  bad "ssot-validate-all.mjs failed (run manually for details)"
fi
if python3 scripts/ssot-validate-refs.py >/dev/null 2>&1; then
  ok "ssot-validate-refs.py — cross-references resolve"
else
  drift "ssot-validate-refs.py reports unresolved refs"
fi
if bash scripts/ssot-validate-sync.sh >/dev/null 2>&1; then
  ok "ssot-validate-sync.sh — SSOT/sync in step"
else
  drift "ssot-validate-sync.sh reports drift"
fi

hdr "T0 — Modularity policy"
SSOT_MOD=$(mget systems.modularity.ssot_cmd)
KB_MOD=$(mget systems.modularity.kb_cmd)
if bash -c "${SSOT_MOD:-node scripts/audits/ssot-modularity-audit.mjs}" >/dev/null 2>&1; then
  ok "ssot-modularity-audit.mjs — SSOT files within modularity thresholds"
else
  drift "ssot-modularity-audit.mjs reports modularity violations (thresholds in ssot.audit.yml)"
fi
if bash -c "${KB_MOD:-node scripts/audits/kb-modularity-audit.mjs}" >/dev/null 2>&1; then
  ok "kb-modularity-audit.mjs — KB entries within modularity thresholds"
else
  drift "kb-modularity-audit.mjs reports modularity violations (thresholds in ssot.audit.yml)"
fi

hdr "T0 — Devin DB + backups"
DB=$(mget systems.devin_db.path); BDIR=$(mget systems.devin_db.backup_dir)
KEEP=$(mget systems.devin_db.keep_backups); MAXG=$(mget systems.devin_db.max_size_gb)
if [ -f "$DB" ]; then
  IC=$(sqlite3 "file:$DB?mode=ro" "PRAGMA integrity_check;" 2>&1 | head -1)
  [ "$IC" = "ok" ] && ok "sessions.db integrity_check: ok" || bad "sessions.db integrity_check: $IC"
  SIZE_G=$(( $(stat -c%s "$DB") / 1024 / 1024 / 1024 ))
  [ "$SIZE_G" -le "$MAXG" ] && ok "sessions.db size ${SIZE_G}G ≤ ${MAXG}G" || drift "sessions.db ${SIZE_G}G exceeds manifest max ${MAXG}G"
else
  bad "sessions.db not found at $DB"
fi
NB=$(ls -1 "$BDIR"/sessions.db.* 2>/dev/null | grep -vc -- '-shm\|-wal')
[ "$NB" -le "$KEEP" ] && ok "backups retained: $NB ≤ $KEEP" || drift "backups retained: $NB > $KEEP (pruning broken?)"

hdr "T0 — Local memory layer"
MEM=$(mget systems.memory_local.session_memory); RAW=$(mget systems.memory_local.raw_dir)
MAXAGE=$(mget systems.memory_local.session_memory_max_age_hours)
HOOK=$(mget systems.memory_local.recall_hook); NLM=$(mget systems.memory_local.nlm_wrapper)
NLMHOST=$(mget systems.memory_local.nlm_expected_host); STUB=$(mget systems.memory_local.stub_marker)

if [ -f "$MEM" ] && [ -s "$MEM" ]; then
  AGE_H=$(( ( $(date +%s) - $(stat -c%Y "$MEM") ) / 3600 ))
  [ "$AGE_H" -le "$MAXAGE" ] && ok "session-memory.md fresh (${AGE_H}h ≤ ${MAXAGE}h)" || drift "session-memory.md stale (${AGE_H}h > ${MAXAGE}h)"
else
  bad "session-memory.md missing/empty: $MEM"
fi

STUBS=$(grep -rl "$STUB" "$RAW" 2>/dev/null | wc -l)
[ "$STUBS" -eq 0 ] && ok "no metadata-stub summaries in raw/" || drift "$STUBS stub summary file(s) in $RAW (rerun those sessions)"

if echo '{"session_id":"smoke","hook_event_name":"SessionStart"}' | DEVIN_PROJECT_DIR="$REPO_ROOT" bash "$HOOK" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'additionalContext' in d['hookSpecificOutput']" 2>/dev/null; then
  ok "notebooklm-recall.sh emits valid additionalContext JSON"
else
  bad "notebooklm-recall.sh did not emit additionalContext"
fi

grep -q "NLM_HOST:-$NLMHOST" "$NLM" && ok "nlm wrapper defaults to $NLMHOST" || drift "nlm wrapper no longer defaults to $NLMHOST — check $NLM"

fi # end T0 block

if [ "$TIER" = "t0" ]; then
  echo
  echo "T0 done. Run with 't1' for auth/service checks."
  echo -e "\n${BLUE}Summary:${NC} $PASS passed, $FAIL failed, $DRIFT drift, $SKIP skipped"
  [ "$FAIL" -eq 0 ]
  exit $?
fi

# ---------- T1 ----------
hdr "T1 — NotebookLM archive (auth required)"
ARCH=$(mget systems.notebooklm.archive_notebook)
MINSRC=$(mget systems.notebooklm.min_sources)
PREFIX=$(mget systems.notebooklm.staging_prefix)
MAXSTG=$(mget systems.notebooklm.max_staging_notebooks)
CQ=$(mget systems.notebooklm.canary_query)
CE=$(mget systems.notebooklm.canary_expect_substring)

LIST=$(nlm notebook list --json 2>/dev/null)
if [ -z "$LIST" ] || echo "$LIST" | grep -qi "Authentication"; then
  skip "nlm auth expired — re-auth via chrome-devtools MCP harvest (see ssot.devin.maintenance.yml reauth_runbook)"
else
  while IFS= read -r line; do
    case "$line" in
      OK:*)    ok "${line#OK: }" ;;
      DRIFT:*) drift "${line#DRIFT: }" ;;
      FAIL:*)  bad "${line#FAIL: }" ;;
    esac
  done < <(echo "$LIST" | python3 - "$ARCH" "$MINSRC" "$PREFIX" "$MAXSTG" <<'PYEOF'
import json, sys
arch, minsrc, prefix, maxstg = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
try:
    nbs = json.load(sys.stdin)
except Exception:
    print("FAIL: could not parse nlm notebook list output"); sys.exit(0)
found = None; staging = 0
for nb in nbs:
    if nb.get('id') == arch: found = nb
    if nb.get('title', '').startswith(prefix): staging += 1
if not found:
    print(f"FAIL: archive notebook {arch} not found")
elif found.get('source_count', 0) < minsrc:
    print(f"DRIFT: archive sources {found.get('source_count')} < baseline {minsrc}")
else:
    print(f"OK: archive sources {found.get('source_count')} >= {minsrc}")
if staging > maxstg:
    print(f"DRIFT: {staging} orphan staging-* notebooks (>{maxstg})")
else:
    print(f"OK: staging orphans: {staging}")
PYEOF
)
fi

hdr "T1 — NotebookLM canary recall"
if [ -z "$LIST" ] || echo "$LIST" | grep -qi "Authentication"; then
  skip "canary query skipped (no auth)"
else
  ANS=$(nlm query notebook "$ARCH" "$CQ" --new-conversation --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('answer',''))" 2>/dev/null)
  if echo "$ANS" | grep -qi "$CE"; then
    ok "canary query contains '$CE'"
  elif [ -n "$ANS" ]; then
    drift "canary query answered but missing '$CE'"
  else
    bad "canary query returned empty answer"
  fi
fi

hdr "T1 — MDDB"
MH=$(mget systems.mddb.health_url); VS=$(mget systems.mddb.vector_search_url)
MINC=$(mget systems.mddb.min_collections); MINSC=$(mget systems.mddb.min_top_score)
MCOL=$(mget systems.mddb.canary_collection); MQ=$(mget systems.mddb.canary_query)
if curl -sf -m 10 "$MH" >/dev/null 2>&1; then
  ok "MDDB health endpoint up"
  NCOL=$(curl -sf -m 30 "http://127.0.0.1:11023/v1/stats" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); c=d.get('collections',[]); print(len(c) if isinstance(c,list) else c)" 2>/dev/null || echo "?")
  [ "$NCOL" != "?" ] && [ "$NCOL" -ge "$MINC" ] 2>/dev/null && ok "MDDB collections: $NCOL ≥ $MINC" || drift "MDDB collections: $NCOL (expected ≥$MINC)"
  VOUT=$(curl -s -m 15 -X POST "$VS" -H "Content-Type: application/json" \
       -d "{\"query\":\"$MQ\",\"limit\":3,\"collection\":\"$MCOL\"}" 2>/dev/null)
  SC=$(echo "$VOUT" | python3 -c "import json,sys; r=json.load(sys.stdin).get('results',[]); print(r[0]['score'] if r else 0)" 2>/dev/null || echo "0")
  VERR=$(echo "$VOUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('error',''))" 2>/dev/null)
  CMP=$(python3 -c "print(1 if float('${SC:-0}') >= $MINSC else 0)" 2>/dev/null || echo 0)
  if [ "$CMP" = "1" ]; then
    ok "MDDB canary score $SC ≥ $MINSC"
  elif [ -n "$VERR" ]; then
    drift "MDDB vector-search error: $VERR"
  else
    drift "MDDB canary score $SC < $MINSC"
  fi
else
  drift "MDDB declared but unreachable at $MH"
fi

hdr "T1 — Weaviate"
WU=$(mget systems.weaviate.url); WC=$(mget systems.weaviate.collection); WMIN=$(mget systems.weaviate.min_objects)
if curl -sf -m 10 "$WU/v1/.well-known/ready" >/dev/null 2>&1 || curl -sf -m 10 "$WU/v1/meta" >/dev/null 2>&1; then
  ok "Weaviate reachable"
  CNT=$(curl -sf -m 15 -X POST "$WU/v1/graphql" -H "Content-Type: application/json" \
        -d "{\"query\":\"{Aggregate{$WC{meta{count}}}}\"}" 2>/dev/null \
        | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['Aggregate']['$WC'][0]['meta']['count'])" 2>/dev/null || echo "?")
  [ "$CNT" != "?" ] && [ "$CNT" -ge "$WMIN" ] 2>/dev/null && ok "Weaviate $WC objects: $CNT ≥ $WMIN" || drift "Weaviate $WC objects: $CNT (expected ≥$WMIN)"
else
  drift "Weaviate declared but unreachable at $WU"
fi

hdr "T1 — MCP smoke suite"
for p in scripts/mcp-debug-server-smoke.py scripts/test-focus-smoke.py; do
  if [ -f "$p" ]; then
    python3 "$p" >/dev/null 2>&1 && ok "$p" || drift "$p reported issues"
  else
    skip "$p not found"
  fi
done

echo
echo -e "${BLUE}Summary:${NC} $PASS passed, $FAIL failed, $DRIFT drift, $SKIP skipped"
echo "DRIFT = live state differs from manifest — update ssot.test-manifest.yml if intentional."
[ "$FAIL" -eq 0 ]
exit $?
