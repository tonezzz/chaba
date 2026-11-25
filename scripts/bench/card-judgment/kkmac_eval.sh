#!/usr/bin/env bash
# kkmac_eval.sh — card kk-mac-card-judgment-eval
#
# Runs the card-judgment corpus (115 shadow cases) against kk-mac's local
# ollama, comparing its models against the llama3.2:3b baseline and the
# paid-flash lane it could replace. Zero spend.
#
# Gates (all must pass — member device, fails closed):
#   1. kk-mac answers ssh over tailnet (kkkakk@kk-mac) AND ollama :11434
#      is serving — machine awake + daemon up.
#   2. Target model is actually pulled on kk-mac (/api/tags).
#   3. Corpus exists locally (rebuild with build_corpus.py if stale).
#
# Run from any tailnet host with the chaba checkout, e.g. tony-omen:
#   scripts/bench/card-judgment/kkmac_eval.sh                     # auto: all pulled kk models
#   scripts/bench/card-judgment/kkmac_eval.sh qwen3:8b llama3.2:3b
#
# Results land next to the corpus as run-kkmac-<model>.{md,json};
# comment them onto the card with:
#   curl -X POST $BOARD_API/comment -d '{"id":"kk-mac-card-judgment-eval",...}'
set -euo pipefail

KK_HOST="${KK_MAC_HOST:-kk-mac}"
KK_USER="${KK_MAC_USER:-kkkakk}"
KK_OLLAMA="${KK_MAC_OLLAMA:-http://kk-mac:11434}"   # tailnet direct
PREFER=(qwen3:8b qwen2.5:32b llama3.2:3b qwen2.5vl:7b)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CORPUS="$SCRIPT_DIR/corpus.jsonl"

cd "$REPO_ROOT"

echo "[gate] ssh $KK_USER@$KK_HOST (or direct ollama probe)"
if ssh -o BatchMode=yes -o ConnectTimeout=6 "$KK_USER@$KK_HOST" true 2>/dev/null; then
  SSH_OK=1
else
  SSH_OK=0
  echo "  ssh denied/unreachable — falling back to direct ollama probe"
fi

if [ "$SSH_OK" = 1 ]; then
  TAGS=$(ssh -o BatchMode=yes "$KK_USER@$KK_HOST" \
    'curl -s -m5 http://127.0.0.1:11434/api/tags' \
    | python3 -c 'import json,sys;print("\n".join(m["name"] for m in json.load(sys.stdin).get("models",[])))') \
    || { echo "ollama not answering on kk-mac:11434 — abort"; exit 2; }
else
  TAGS=$(curl -s -m5 "$KK_OLLAMA/api/tags" \
    | python3 -c 'import json,sys;print("\n".join(m["name"] for m in json.load(sys.stdin).get("models",[])))' 2>/dev/null) \
    || { echo "ollama not answering on $KK_OLLAMA — abort (offline/asleep?)"; exit 2; }
  [ -n "$TAGS" ] || { echo "ollama probe returned no models — abort"; exit 2; }
fi
echo "$TAGS" | sed 's/^/  pulled: /'

MODELS=("$@")
if [ ${#MODELS[@]} -eq 0 ]; then
  for p in "${PREFER[@]}"; do
    grep -qx "$p" <<<"$TAGS" && MODELS+=("$p")
  done
fi
[ ${#MODELS[@]} -gt 0 ] || { echo "no preferred models pulled on kk-mac — abort"; exit 2; }
echo "[plan] evaluating: ${MODELS[*]}"

for m in "${MODELS[@]}"; do
  tag=$(echo "$m" | tr -cd '[:alnum:]-' | tr ':' '-')
  out_md="$SCRIPT_DIR/run-kkmac-$tag.md"
  out_json="$SCRIPT_DIR/run-kkmac-$tag.json"
  echo "[run] $m -> $out_md"
  TEMP_ARGS=()
  [ "$SSH_OK" = 1 ] && TEMP_ARGS=(--temp-host "$KK_HOST" --temp-ssh-user "$KK_USER"
    --max-temp-c "${KK_MAC_MAX_TEMP_C:-60}")
  python3 "$SCRIPT_DIR/score.py" \
    --entity openai --model "$m" \
    --base-url "http://$KK_HOST:11434/v1" \
    "${TEMP_ARGS[@]}" \
    --corpus "$CORPUS" \
    --out-md "$out_md" --out-json "$out_json" \
    || echo "  model $m failed (see stderr) — continuing"
done

echo "[done] reports written next to corpus: $SCRIPT_DIR/run-kkmac-*.md"
