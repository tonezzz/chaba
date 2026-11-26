#!/usr/bin/env bash
# healthcheck.sh — verify each layer of the Jack LLM stack.
# Sources mock/.env.mock when present (mock deploy), else env vars/.env.
set -u
cd "$(dirname "$0")"

if [ -f mock/.env.mock ]; then
  set -a; . ./mock/.env.mock; set +a
elif [ -f .env ]; then
  set -a; . ./.env; set +a
fi

OLLAMA="${JACK_OLLAMA_URL:-http://127.0.0.1:11434}"
LITELLM="${JACK_LITELLM_URL:-http://127.0.0.1:4000}"
MODEL="${JACK_OLLAMA_MODEL:-qwen2.5:3b}"
ALIAS="${JACK_LITELLM_ALIAS:-jack-chat}"
KEY="${JACK_LITELLM_API_KEY:-CHANGE_ME_LITELLM_KEY}"

fails=0
ok()   { echo "PASS  $1"; }
bad()  { echo "FAIL  $1"; fails=$((fails+1)); }

# 1. Ollama reachable + model present
if curl -fsS -m 5 "$OLLAMA/api/tags" -o /tmp/jack-tags.json 2>/dev/null \
   && grep -q "$MODEL" /tmp/jack-tags.json; then
  ok "ollama reachable, model $MODEL present"
else
  bad "ollama unreachable or model $MODEL missing at $OLLAMA"
fi

# 2. LiteLLM liveliness
if curl -fsS -m 5 "$LITELLM/health/liveliness" >/dev/null 2>&1; then
  ok "litellm liveliness at $LITELLM"
else
  bad "litellm liveliness failed at $LITELLM"
fi

# 3. LiteLLM chat round-trip through the alias
resp=$(curl -fsS -m 30 -X POST "$LITELLM/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$ALIAS\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":8}" 2>/dev/null)
if echo "$resp" | grep -q '"content"'; then
  ok "litellm chat completion via alias $ALIAS"
else
  bad "litellm chat completion failed via alias $ALIAS"
fi

# 4. OpenCode provider config parses and points at the right endpoint
if command -v python3 >/dev/null && [ -f opencode/opencode.json ]; then
  if JACK_WANT_URL="$LITELLM" python3 - <<'PY'
import json, os, re, sys
want = os.environ["JACK_WANT_URL"].rstrip("/")
cfg = json.load(open("opencode/opencode.json"))

def resolve(s):
    return re.sub(r"\{env:([A-Z0-9_]+)\}",
                  lambda m: os.environ.get(m.group(1), ""), str(s))

hits = []
for p, v in cfg.get("provider", {}).items():
    base = resolve(v.get("options", {}).get("baseURL", ""))
    if want in base:
        hits.append(p)
sys.exit(0 if hits else 1)
PY
  then
    ok "opencode provider config targets $LITELLM"
  else
    bad "opencode provider config missing/mismatched endpoint"
  fi
else
  bad "python3 or opencode/opencode.json missing"
fi

echo "---"
if [ "$fails" -eq 0 ]; then echo "healthcheck: ALL PASS"; else
  echo "healthcheck: $fails FAILURES"; fi
exit "$fails"
