#!/usr/bin/env bash
# Chaba lightweight CI smoke suite.
# Runs the checks that are fast and safe: SSOT validation, memory recall
# canary, memory unit tests, and the developer-recall live scenario.
# Exit 0 if all pass, 1 if any fail.

set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADA_PI="/home/tony/CascadeProjects/ada-pi"
SUMMARY=()
PASS=0

run_check() {
    local name="$1"
    shift
    if "$@" >/tmp/ci-smoke-last.out 2>&1; then
        SUMMARY+=("[PASS] $name")
        ((PASS++))
        return 0
    else
        SUMMARY+=("[FAIL] $name")
        cat /tmp/ci-smoke-last.out
        return 1
    fi
}

# 1. SSOT validation
run_check "SSOT validation" node "$ROOT/scripts/ssot-validate-all.mjs" || true

# 2. Ada recall canary
run_check "recall canary" python3 "$ROOT/scripts/ada/recall-canary.py" --json /tmp/recall-canary-ci.json || true

# 3. Memory script unit tests
run_check "memory unit tests" python3 -m pytest "$ROOT/tests/ada_memory/test_memory_scripts.py" -q || true

# 4. Developer recall live scenario on ada-pi-pwa (tony instance)
run_check "developer recall scenario" \
    ssh -o BatchMode=yes -o ConnectTimeout=10 idc01 \
    "set -a; . /home/tony/.config/secrets/ada-pi-pwa.env; \
     $ADA_PI/.venv/bin/python $ADA_PI/scripts/scenario-live.py \
       --url ws://127.0.0.1:8001/ws \
       $ADA_PI/tests/scenarios-live/developer_recall_runbook.yaml" || true

TOTAL=${#SUMMARY[@]}
FAIL=$((TOTAL - PASS))

echo
echo "=== CI Smoke Summary ==="
for line in "${SUMMARY[@]}"; do
    echo "$line"
done
echo "=== $PASS/$TOTAL passed ==="

[ "$PASS" -eq "$TOTAL" ]
