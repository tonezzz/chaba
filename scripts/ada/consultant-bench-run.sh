#!/usr/bin/env bash
# Run consultant-bench over the first-filter candidate models on the grown
# fixture. Host-side: needs LiteLLM reachable (LITELLM_URL/LITELLM_KEY env).
#
#   scripts/ada/consultant-bench-run.sh                      # all candidates
#   scripts/ada/consultant-bench-run.sh ollama-qwen38b-kkmac # subset
#
# Extra args to consultant-bench.py (e.g. --max-tokens for thinking models)
# via BENCH_ARGS env: BENCH_ARGS="--max-tokens 64" scripts/ada/consultant-bench-run.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

FIXTURE="${FIXTURE:-fixtures/consultant-tasks.jsonl}"
DEFAULT_MODELS="ollama-qwen38b-kkmac ollama-deepseek-v32-kkmac or-claude-fable-5.1"

if [ "$#" -gt 0 ]; then
    MODELS="$*"
else
    MODELS="${MODELS:-$DEFAULT_MODELS}"
fi

python3 scripts/ada/consultant-fixture-validate.py "$FIXTURE"

for m in $MODELS; do
    echo "=== $m ==="
    # shellcheck disable=SC2086
    python3 scripts/ada/consultant-bench.py --model "$m" --fixture "$FIXTURE" ${BENCH_ARGS:-}
done
