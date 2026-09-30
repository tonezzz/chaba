#!/usr/bin/env bash
# Combined CI entry: run smoke, standardization, and QA/QC gates.
# Exit 0 only if every gate passes.

set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUITES=("$ROOT/scripts/ci-smoke.sh" "$ROOT/scripts/ci-standard.sh" "$ROOT/scripts/ci-qa.sh")
FAIL=0

echo "=== CI Suite ==="
for suite in "${SUITES[@]}"; do
    name="$(basename "$suite" .sh)"
    echo "--- $name ---"
    if "$suite"; then
        echo "$name: PASS"
    else
        echo "$name: FAIL"
        FAIL=1
    fi
    echo
done

echo "=== CI Suite Result: $([ $FAIL -eq 0 ] && echo PASS || echo FAIL) ==="
exit $FAIL
