#!/usr/bin/env bash
# mint-key.sh — create a LiteLLM virtual key with a budget on idc03.
# Usage: mint-key.sh <alias> <max_budget_usd> <budget_duration> [models-csv]
#   mint-key.sh ada 10 30d "gemini-2.5-flash,gemini-3.5-flash-lite,tool-call,summary,voice-aux,classify,vision,embedding"
# Prints the minted sk- key; append to ~/.config/secrets/litellm-keys.env on idc03.
set -euo pipefail
ALIAS="${1:?alias}"; BUDGET="${2:?usd}"; DUR="${3:?duration}"; MODELS="${4:-}"
GW="${LITELLM_URL:-http://100.102.134.91:4000}"

read -r -d '' JQ <<PY || true
import json,sys
models = "${MODELS}".strip()
print(json.dumps({"key_alias": "${ALIAS}", "max_budget": float("${BUDGET}"),
                  "budget_duration": "${DUR}",
                  **({"models": models.split(",")} if models else {})}))
PY
BODY="$(python3 -c "$JQ")"

KEY="$(ssh -o BatchMode=yes idc03 'grep -oP "^LITELLM_MASTER_KEY=\K.*" ~/.config/secrets/litellm.env')"
NEWKEY="$(curl -sf -X POST "$GW/key/generate" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['key'])")"

# dependent env sync (OPS-1291): services that pin LITELLM_KEY in a
# per-service secrets file must follow rotation or they break at next
# restart (ada-code outage 2026-11-09). Map: alias -> host envfile unit.
case "$ALIAS" in
  ada|ada-code)
    ssh -o BatchMode=yes -o ConnectTimeout=8 idc02       "grep -q LITELLM_KEY ~/.config/secrets/ada-code.env \
        && sed -i 's|^LITELLM_KEY=.*|LITELLM_KEY='"$NEWKEY"'|' ~/.config/secrets/ada-code.env \
        || echo LITELLM_KEY=$NEWKEY >> ~/.config/secrets/ada-code.env; \
       systemctl --user restart ada-code.service" \
      && echo "dependent synced: idc02 ada-code.env + ada-code.service restarted" \
      || echo "WARN: dependent sync failed for ada-code (idc02) — update ada-code.env manually" >&2
    ;;
esac
printf '%s\n' "$NEWKEY"
