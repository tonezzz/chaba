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
curl -sf -X POST "$GW/key/generate" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['key'])"
