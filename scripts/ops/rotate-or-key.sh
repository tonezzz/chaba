#!/usr/bin/env bash
# rotate-or-key.sh — swap the weekly OpenRouter key across all 4 stores,
# restart env-baked services, verify e2e.
#
# Card: rotate-or-key-script. Procedure verified live 2026-10-10.
#
# Usage:  Tony mints the next key at openrouter.ai/keys, drops it into
#         ~/.config/secrets/or-next-key (any file containing the sk-or-v1-*
#         token), then:  rotate-or-key.sh [keyfile]
#
# NEVER pass the key itself as an argument — argv lands in ps/history.
# On remotes the key travels only over ssh stdin.
set -euo pipefail

STORE_LOCAL="$HOME/.config/secrets/openrouter.env"   # store 1 (tony-dell)
HOST_OMEN="tony-omen"                                # store 2 + sqlite
HOST_IDC03="idc03"                                   # store 3 + proxy restart
OMEN_ENV='~/.config/secrets/openrouter.env'
IDC03_ENV='~/.config/secrets/mddb-gemini.env'
OMEN_SQLITE='~/.openclaw/state/openclaw.sqlite'

say()  { printf '%s\n' "$*"; }
die()  { printf 'rotate-or-key: %s\n' "$*" >&2; exit 1; }
mask() { printf 'sk-or-v1-…%s' "${1: -4}"; }

# ── input: key from file, never argv ───────────────────────────────
case "${1:-}" in
  sk-*) die "key passed as argument — put it in ~/.config/secrets/or-next-key" ;;
esac
KEYFILE="${1:-$HOME/.config/secrets/or-next-key}"
[ -f "$KEYFILE" ] || die "no keyfile at $KEYFILE — mint at openrouter.ai/keys first"
KEY=$(grep -oE 'sk-or-v1-[A-Za-z0-9_-]+' "$KEYFILE" | head -1)
[ -n "$KEY" ] || die "no sk-or-v1-* token found in $KEYFILE"
say "key: $(mask "$KEY")  from $KEYFILE"

# ── in-place env merge: replaces the OPENROUTER_API_KEY= line,
#    preserves everything else (incl. commented lines). ─────────────
merge_script='while IFS= read -r line; do
  case "$line" in
    OPENROUTER_API_KEY=*) printf "OPENROUTER_API_KEY=%s\n" "$NEWKEY" ;;
    *) printf "%s\n" "$line" ;;
  esac
done < "$F" > "$F.new" && chmod 600 "$F.new" && mv "$F.new" "$F"'

merge_env_remote() {  # $1 host  $2 remote env path — key rides stdin only
  { printf 'NEWKEY=%q\n' "$KEY"; printf 'F=%s\n' "$2"; printf '%s\n' "$merge_script"; } \
    | ssh -o BatchMode=yes -o ConnectTimeout=8 "$1" 'bash -s' \
    || die "env merge failed on $1"
}

# ── precheck: is the new key valid before we swap anything? ────────
say "→ verifying key against openrouter.ai/api/v1/auth/key"
auth_json=$(curl -sf -m 15 https://openrouter.ai/api/v1/auth/key \
  -H "Authorization: Bearer $KEY") || die "key rejected by openrouter (or network down)"
echo "$auth_json" | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print('   label:', d.get('label'), '| expires:', d.get('expires_at'))"

# ── store 1: tony-dell (local) ─────────────────────────────────────
[ -f "$STORE_LOCAL" ] || die "$STORE_LOCAL missing"
# capture the outgoing fleet key before the merge — the ada-*.env sweep
# below replaces only lines still holding it, sparing per-lane keys
OLDKEY=$(grep -oE 'sk-or-v1-[A-Za-z0-9_-]+' "$STORE_LOCAL" | head -1 || true)
NEWKEY="$KEY" F="$STORE_LOCAL" bash -c "$merge_script"
say "✓ store 1: $STORE_LOCAL"

# ── store 2: tony-omen env ─────────────────────────────────────────
merge_env_remote "$HOST_OMEN" "$OMEN_ENV"
say "✓ store 2: omen $OMEN_ENV"

# ── store 3: idc03 mddb-gemini.env (keeps commented line 4) ────────
merge_env_remote "$HOST_IDC03" "$IDC03_ENV"
say "✓ store 3: idc03 $IDC03_ENV"

# ── store 4: openclaw sqlite on omen (key via stdin, not argv) ─────
{ printf 'KEY = "%s"\n' "$KEY"; cat <<'PYEOF'
import sqlite3, os
db = os.path.expanduser("~/.openclaw/state/openclaw.sqlite")
con = sqlite3.connect(db)
n = con.execute("""UPDATE config_machine_state
                   SET value_json = json_replace(value_json,
                     '$.profiles."openrouter:manual".key', ?),
                       updated_at_ms = CAST(strftime('%s','now') AS INTEGER)*1000
                   WHERE state_key = 'authProfiles.store'""", (KEY,)).rowcount
con.commit(); con.close()
print("   sqlite authProfiles.store updated" if n else "   !! no authProfiles.store row")
PYEOF
} | ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST_OMEN" 'python3 -' \
  || die "sqlite update failed on omen"
say "✓ store 4: omen openclaw sqlite"

# ── ada backends on idc03: ada-*.env files also carry OR fallback keys
#    (openrouter_provider.py degraded mode). Found stale 2026-10-12 —
#    the 4-store set missed them and all ada OR fallbacks were 401.
#    Sweep only files still holding the OLD fleet key so per-lane keys
#    (e.g. kaewta-daily in ada-kk.env) survive rotations. ─────────────
if [ -n "$OLDKEY" ]; then
  { printf 'OLDKEY=%q\nNEWKEY=%q\n' "$OLDKEY" "$KEY"; cat <<'SWEEP'
for F in ~/.config/secrets/ada-*.env; do
  [ -f "$F" ] || continue
  if grep -qF "$OLDKEY" "$F"; then
    sed -i "s|^OPENROUTER_API_KEY=.*|OPENROUTER_API_KEY=$NEWKEY|" "$F"
    echo "swept $(basename "$F" .env)"
  fi
done
SWEEP
  } | ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST_IDC03" 'bash -s' \
    | tee /tmp/or-swept-units.$$.txt >/dev/null
  SWEPT=$(grep -oE 'swept [a-z-]+' /tmp/or-swept-units.$$.txt | awk '{print $2}' || true)
  rm -f /tmp/or-swept-units.$$.txt
  for u in $SWEPT; do
    # try-restart: never starts a stopped lane (ada-ha-tony may be down)
    ssh -o BatchMode=yes "$HOST_IDC03" "systemctl --user try-restart $u" \
      && say "✓ try-restarted $u (swept env)"
  done
  [ -z "$SWEPT" ] && say "· no ada-*.env held the old key — nothing to sweep"
else
  say "· no prior OR key in $STORE_LOCAL — skipping ada-*.env sweep"
fi

# ── restarts (env-baked services only) ─────────────────────────────
ssh -o BatchMode=yes "$HOST_OMEN"  'systemctl --user restart ghostroute-watcher' \
  && say "✓ restarted ghostroute-watcher (omen)"
ssh -o BatchMode=yes "$HOST_IDC03" 'systemctl --user restart gemini-ollama-proxy' \
  && say "✓ restarted gemini-ollama-proxy (idc03)"
# litellm mounts the same mddb-gemini.env for OPENROUTER_API_KEY
if ssh -o BatchMode=yes "$HOST_IDC03" \
     'systemctl --user is-active --quiet litellm'; then
  ssh -o BatchMode=yes "$HOST_IDC03" 'systemctl --user restart litellm' \
    && say "✓ restarted litellm (idc03)"
fi
# ── openclaw-gateway caches the auth profile key at STARTUP. The sqlite
#    store changing is not enough: 2026-11-23 all 4 stores were correct but
#    a live agent turn still 401d until the gateway was restarted. ──────
ssh -o BatchMode=yes "$HOST_OMEN" 'systemctl --user restart openclaw-gateway' \
  && say "✓ restarted openclaw-gateway (omen — caches authProfiles.store)"

# systemd reports active ~15s before the loopback listener binds
# (observed ~30s total warm-up); don't probe a dead socket.
say "→ waiting for openclaw-gateway on 127.0.0.1:18789"
GW_READY=0
for _ in $(seq 1 30); do
  if ssh -o BatchMode=yes "$HOST_OMEN" \
       'ss -ltn 2>/dev/null | grep -q "127.0.0.1:18789"'; then
    GW_READY=1
    break
  fi
  sleep 2
done
[ "$GW_READY" -eq 1 ] || die "openclaw-gateway did not bind 127.0.0.1:18789 within 60s"
say "✓ gateway listener ready"

# ── e2e: :free chat call (free slugs churn — query live list) ───────
# Two independent failure modes seen 2026-11-24: a single model can 429,
# and the ACCOUNT-wide free-tier daily quota can be exhausted (then every
# :free model 429s). google/* free models can also 400 on an invalid
# upstream Google key — exclude them. Only 401 is a stale-key signature.
say "→ e2e: :free model call"
FREE_MODELS=$(curl -sf -m 20 https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer $KEY" \
  | python3 -c "import json,sys; print(' '.join([m['id'] for m in json.load(sys.stdin)['data'] if m['id'].endswith(':free') and not m['id'].startswith('google/')][:5]))") \
  || die "no :free model found in catalog"
E2E_OK=0; QUOTA_OUT=0
for FREE_MODEL in $FREE_MODELS; do
  [ "$E2E_OK" -eq 1 ] && break
  say "   trying $FREE_MODEL"
  # capture body + status separately; -sf would hide the 429 body we need
  RESP=$(curl -s -m 30 -w '\n%{http_code}' https://openrouter.ai/api/v1/chat/completions \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"$FREE_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"reply with the single word ok\"}],\"max_tokens\":128}" 2>/dev/null) \
    || { say "   network error — next"; continue; }
  CODE=$(printf '%s' "$RESP" | tail -1)
  BODY=$(printf '%s' "$RESP" | sed '$d')
  case "$CODE" in
    200)
      # reasoning models burn max_tokens on `reasoning` (content:null)
      REPLY=$(printf '%s' "$BODY" | python3 -c "import json,sys; m=json.load(sys.stdin)['choices'][0]['message']; print((m.get('content') or m.get('reasoning') or '').strip()[:40] or '(empty)')" 2>/dev/null) \
        || REPLY='(unparseable)'
      say "   reply: $REPLY"; E2E_OK=1 ;;
    401|403) die "e2e auth failure ($CODE) — key not live: $(printf '%s' "$BODY" | head -c 200)" ;;
    429)
      printf '%s' "$BODY" | grep -q 'free-models-per-day' && QUOTA_OUT=1
      say "   upstream rejected $FREE_MODEL (429) — next" ;;
    *) say "   upstream rejected $FREE_MODEL ($CODE) — next" ;;
  esac
done
if [ "$E2E_OK" -eq 1 ]; then
  say "✓ e2e direct call OK"
elif [ "$QUOTA_OUT" -eq 1 ]; then
  say "· e2e DEFERRED: OR free-tier DAILY quota exhausted (resets 07:00 ICT) — key precheck passed"
else
  die "e2e call failed across all :free models — check per-store files above"
fi

# A direct HTTP call only proves the KEY works — not that the gateway
# picked it up. Drive one real agent turn through the gateway as the
# final gate (throwaway session, no delivery to a channel). Pin an
# explicit model — the default fallback chain drifts into google/*:free
# models that 400 on an invalid upstream Google key and burn all retries.
GW_OK=0
for FREE_MODEL in $FREE_MODELS; do
  [ "$GW_OK" -eq 1 ] && break
  [ "$QUOTA_OUT" -eq 1 ] && { say "· gateway probe skipped: free quota exhausted (resets 07:00 ICT)"; break; }
  say "→ gateway probe turn: $FREE_MODEL"
  GW_PROBE=$(ssh -o BatchMode=yes "$HOST_OMEN" \
     "timeout 100 ~/.npm-global/bin/openclaw agent --session-key agent:main:or-rotation-probe --model 'openrouter/$FREE_MODEL' --message 'Reply with the single word OK.' --json --timeout 80" 2>&1) \
    || GW_PROBE="${GW_PROBE:-ssh failed}"
  if printf '%s' "$GW_PROBE" | grep -qE '"status"[[:space:]]*:[[:space:]]*"ok"|"ok"[[:space:]]*:[[:space:]]*true'; then
    say "✓ gateway probe turn OK ($FREE_MODEL)"; GW_OK=1
  elif printf '%s' "$GW_PROBE" | grep -qiE '401|invalid.*api.?key|authentication.*fail'; then
    die "gateway probe turn rejected the key — old key still cached: $(printf '%s' "$GW_PROBE" | head -c 300)"
  elif printf '%s' "$GW_PROBE" | grep -qiE 'rate limit|429'; then
    say "   $FREE_MODEL rate-limited — next"
  else
    say "   gateway probe inconclusive — next: $(printf '%s' "$GW_PROBE" | head -c 160)"
  fi
done
if [ "$GW_OK" -eq 0 ] && [ "$QUOTA_OUT" -ne 1 ]; then
  die "gateway probe failed across all :free models — old key may still be cached"
fi

say "done — $(mask "$KEY") live in all 4 stores"
