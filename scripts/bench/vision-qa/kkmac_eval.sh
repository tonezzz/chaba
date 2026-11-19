#!/usr/bin/env bash
# kkmac_eval.sh — card kk-mac-vision-lane-eval
#
# Runs the vision-qa corpus (~18 synthetic cases: stock-asset description
# match + defect detection, UI screenshot triage) against kk-mac's local
# ollama VLM. Verdict: is qwen2.5vl:7b usable for the adobe-stock visual
# QA lane? Zero spend, member-device gated.
#
# Gates (all must pass — member device, fails closed):
#   1. kk-mac answers ssh over tailnet (kkkakk@kk-mac) AND ollama :11434
#      is serving — machine awake + daemon up.
#   2. A vision model is actually pulled on kk-mac (/api/tags).
#   3. Corpus exists locally (rebuild: build_corpus.py in this dir).
#
# Run from any tailnet host with the chaba checkout:
#   scripts/bench/vision-qa/kkmac_eval.sh                     # qwen2.5vl:7b
#   scripts/bench/vision-qa/kkmac_eval.sh qwen2.5vl:7b llava:7b
#
# Results land next to the corpus as run-kkmac-<model>.{md,json};
# comment them onto the card with:
#   curl -X POST $BOARD_API/comment -d '{"id":"kk-mac-vision-lane-eval",...}'
set -euo pipefail

KK_HOST="${KK_MAC_HOST:-kk-mac}"
KK_USER="${KK_MAC_USER:-kkkakk}"
PREFER=(qwen2.5vl:7b llava:7b llava:13b moondream:latest minicpm-v:latest)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CORPUS="$SCRIPT_DIR/corpus.jsonl"

cd "$REPO_ROOT"

echo "[gate] ssh $KK_USER@$KK_HOST"
ssh -o BatchMode=yes -o ConnectTimeout=6 "$KK_USER@$KK_HOST" true \
  || { echo "kk-mac unreachable (offline/asleep?) — abort, nothing ran"; exit 2; }

echo "[gate] ollama tags"
TAGS=$(ssh -o BatchMode=yes "$KK_USER@$KK_HOST" \
  'curl -s -m5 http://127.0.0.1:11434/api/tags' \
  | python3 -c 'import json,sys;print("\n".join(m["name"] for m in json.load(sys.stdin).get("models",[])))') \
  || { echo "ollama not answering on kk-mac:11434 — abort"; exit 2; }
echo "$TAGS" | sed 's/^/  pulled: /'

MODELS=("$@")
if [ ${#MODELS[@]} -eq 0 ]; then
  for p in "${PREFER[@]}"; do
    grep -qx "$p" <<<"$TAGS" && MODELS+=("$p")
  done
fi
[ ${#MODELS[@]} -gt 0 ] || { echo "no vision models pulled on kk-mac — abort"; exit 2; }
echo "[plan] evaluating: ${MODELS[*]}"

[ -f "$CORPUS" ] || { echo "corpus missing — run: python3 $SCRIPT_DIR/build_corpus.py"; exit 2; }

for m in "${MODELS[@]}"; do
  tag=$(echo "$m" | tr -cd '[:alnum:]-' | tr ':' '-')
  out_md="$SCRIPT_DIR/run-kkmac-$tag.md"
  out_json="$SCRIPT_DIR/run-kkmac-$tag.json"
  echo "[run] $m -> $out_md"
  python3 "$SCRIPT_DIR/score.py" \
    --entity ollama --model "$m" \
    --base-url "http://$KK_HOST:11434" \
    --temp-host "$KK_HOST" --temp-ssh-user "$KK_USER" \
    --max-temp-c "${KK_MAC_MAX_TEMP_C:-60}" \
    --corpus "$CORPUS" \
    --out-md "$out_md" --out-json "$out_json" \
    || echo "  model $m failed (see stderr) — continuing"
done

echo "[done] reports written next to corpus: $SCRIPT_DIR/run-kkmac-*.md"
