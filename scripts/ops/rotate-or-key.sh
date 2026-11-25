#!/usr/bin/env bash
# rotate-or-key.sh — rotate the LiteLLM gateway fleet OpenRouter key.
#
# Architecture (card or-direct-bypass-leak-audit, 2026-11-25): the fleet
# OR key lives ONLY in idc03:~/.config/secrets/litellm.env
# (OPENROUTER_API_KEY) — the LiteLLM container's upstream credential for
# or-gemini-embedding-2, or-gemini-3.1-flash-image, consult-claude, the
# or-free-* routes and the `embedding` alias. Every other OR consumer
# holds its own scoped key or rides the gateway:
#   - gemini-ollama-proxy embed OR leg -> LiteLLM /v1/embeddings
#     (EMBED_GATEWAY_* in idc03 mddb-gemini.env)
#   - tony-omen openclaw/ghostroute -> dedicated tony-omen-openclaw-free
#     key ($0.50/wk cap; rotates on its own cadence, NOT by this script)
#   - paid or-* bench/eval routes -> OPENROUTER_BENCH_API_KEY (litellm.env,
#     separate key idc03-litellm-bench, also not touched here)
#
# Usage:  mint the next key at openrouter.ai/keys (or provisioning API),
#         drop it into ~/.config/secrets/or-next-key (any file containing
#         the sk-or-v1-* token), then:  rotate-or-key.sh [keyfile]
#
# NEVER pass the key itself as an argument — argv lands in ps/history.
# On remotes the key travels only over ssh stdin.
set -euo pipefail

HOST_IDC03="idc03"
IDC03_LITELLM_ENV='~/.config/secrets/litellm.env'

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
merge_script='if grep -q "^OPENROUTER_API_KEY=" "$F"; then
  while IFS= read -r line; do
    case "$line" in
      OPENROUTER_API_KEY=*) printf "OPENROUTER_API_KEY=%s\n" "$NEWKEY" ;;
      *) printf "%s\n" "$line" ;;
    esac
  done < "$F" > "$F.new"
else
  cp "$F" "$F.new"
  printf "OPENROUTER_API_KEY=%s\n" "$NEWKEY" >> "$F.new"
fi
chmod 600 "$F.new" && mv "$F.new" "$F"'

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

# ── store: idc03 litellm.env — the ONLY fleet-key store ────────────
merge_env_remote "$HOST_IDC03" "$IDC03_LITELLM_ENV"
say "✓ store: idc03 $IDC03_LITELLM_ENV"

# ── restart litellm (env-file is read at container create) ─────────
ssh -o BatchMode=yes "$HOST_IDC03" 'systemctl --user restart litellm' \
  && say "✓ restarted litellm (idc03)"

# systemd reports active ~15s before the listener binds; give it room.
say "→ waiting for litellm liveliness on 100.102.134.91:4000"
GW_READY=0
for _ in $(seq 1 30); do
  if ssh -o BatchMode=yes "$HOST_IDC03" \
       'curl -sf --max-time 5 http://100.102.134.91:4000/health/liveliness >/dev/null'; then
    GW_READY=1
    break
  fi
  sleep 2
done
[ "$GW_READY" -eq 1 ] || die "litellm did not become live within 60s"
say "✓ litellm liveliness OK"

# ── e2e through the gateway (the only supported OR path now) ───────
# 1) paid-capable route on the fleet key: or-gemini-embedding-2
say "→ e2e: gateway or-gemini-embedding-2 (fleet key upstream)"
EMB=$(ssh -o BatchMode=yes "$HOST_IDC03" 'set -a; . ~/.config/secrets/litellm.env; set +a;
  curl -s -m 40 http://100.102.134.91:4000/v1/embeddings \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"or-gemini-embedding-2\",\"input\":\"rotation e2e\",\"dimensions\":768}"')
printf '%s' "$EMB" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('data'), d; print('   embed dims:', len(d['data'][0]['embedding']))" \
  || die "gateway embedding e2e failed: $(printf '%s' "$EMB" | head -c 300)"
say "✓ gateway embedding e2e OK"

# 2) a :free chat route on the fleet key — skipped when the account-wide
#    OR free-tier daily quota is exhausted (resets 07:00 ICT).
say "→ e2e: gateway or-free chat (fleet key upstream)"
CHAT=$(ssh -o BatchMode=yes "$HOST_IDC03" 'set -a; . ~/.config/secrets/litellm.env; set +a;
  curl -s -m 40 -w "\n%{http_code}" http://100.102.134.91:4000/v1/chat/completions \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"or-free-nemotron-nano\",\"messages\":[{\"role\":\"user\",\"content\":\"reply with the single word ok\"}],\"max_tokens\":16}"')
CODE=$(printf '%s' "$CHAT" | tail -1)
BODY=$(printf '%s' "$CHAT" | sed '$d')
case "$CODE" in
  200) say "✓ gateway chat e2e OK" ;;
  429) say "· gateway chat e2e DEFERRED: OR free-tier daily quota exhausted (key precheck + embed e2e passed)" ;;
  *)   die "gateway chat e2e failed ($CODE): $(printf '%s' "$BODY" | head -c 300)" ;;
esac

say "done — $(mask "$KEY") live in the gateway store (idc03 litellm.env)"
