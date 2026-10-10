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

# ── restarts (env-baked services only) ─────────────────────────────
ssh -o BatchMode=yes "$HOST_OMEN"  'systemctl --user restart ghostroute-watcher' \
  && say "✓ restarted ghostroute-watcher (omen)"
ssh -o BatchMode=yes "$HOST_IDC03" 'systemctl --user restart gemini-ollama-proxy' \
  && say "✓ restarted gemini-ollama-proxy (idc03)"
# openclaw-gateway reads the key from sqlite at call time — restart only
# if it instead sources an env file carrying the key:
if ssh -o BatchMode=yes "$HOST_OMEN" \
     'systemctl --user cat openclaw-gateway 2>/dev/null | grep -q "EnvironmentFile.*openrouter"'; then
  ssh -o BatchMode=yes "$HOST_OMEN" 'systemctl --user restart openclaw-gateway' \
    && say "✓ restarted openclaw-gateway (env-baked key)"
else
  say "· openclaw-gateway: reads sqlite at call time — no restart needed"
fi

# ── e2e: one :free chat call ───────────────────────────────────────
say "→ e2e: :free model call"
curl -sf -m 30 https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3.8-27b:free","messages":[{"role":"user","content":"reply with the single word ok"}],"max_tokens":8}' \
  | python3 -c "import json,sys; print('   reply:', json.load(sys.stdin)['choices'][0]['message']['content'].strip()[:40])" \
  || die "e2e call failed — check per-store files above"

say "done — $(mask "$KEY") live in all 4 stores"
