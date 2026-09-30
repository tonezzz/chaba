#!/usr/bin/env bash
# Chaba QA/QC gate.
# Checks: Python syntax, shell syntax, Node (.mjs) syntax, YAML parse,
# and a lightweight secret-pattern scan over tracked files.
# Exit 0 if all pass, 1 if any fail.

set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUMMARY=()
PASS=0

run_check() {
    local name="$1"
    shift
    if "$@" >/tmp/ci-qa-last.out 2>&1; then
        SUMMARY+=("[PASS] $name")
        ((PASS++))
        return 0
    else
        SUMMARY+=("[FAIL] $name")
        cat /tmp/ci-qa-last.out
        return 1
    fi
}

# 1. Python syntax over all tracked *.py
run_check "python syntax" bash -c '
cd "$1" &&
python3 - <<\PY
import ast
import subprocess
import sys

files = subprocess.check_output(
    ["git", "ls-files", "*.py"], text=True
).splitlines()
bad = []
for f in files:
    try:
        ast.parse(open(f, encoding="utf-8").read(), filename=f)
    except SyntaxError as exc:
        bad.append(f"{f}:{exc.lineno}:{exc.col_offset}: {exc.msg}")
if bad:
    print("Syntax errors:")
    print("\n".join(bad))
    sys.exit(1)
print(f"OK - {len(files)} python files parsed")
PY
' -- "$ROOT" || true

# 2. Shell syntax over all tracked *.sh
run_check "shell syntax" bash -c '
cd "$1" &&
BAD=0
for f in $(git ls-files "*.sh"); do
  bash -n "$f" >/dev/null 2>&1 || { echo "shell syntax: $f"; BAD=1; }
done
exit $BAD
' -- "$ROOT" || true

# 3. Node syntax over all tracked *.mjs
run_check "node syntax" bash -c '
cd "$1" &&
BAD=0
for f in $(git ls-files "*.mjs"); do
  node -c "$f" >/dev/null 2>&1 || { echo "node syntax: $f"; BAD=1; }
done
exit $BAD
' -- "$ROOT" || true

# 4. YAML parse over all tracked *.yml / *.yaml
run_check "yaml parse" bash -c '
cd "$1" &&
python3 - <<\PY
import subprocess
import sys

import yaml


class Lenient(yaml.SafeLoader):
    pass


Lenient.add_multi_constructor("!", lambda l, s, n: None)

files = subprocess.check_output(
    ["git", "ls-files", "*.yml", "*.yaml"], text=True
).splitlines()
bad = []
for f in files:
    try:
        yaml.load(open(f, encoding="utf-8"), Loader=Lenient)
    except Exception as exc:
        bad.append(f"{f}: {exc}")
if bad:
    print("YAML errors:")
    print("\n".join(bad))
    sys.exit(1)
print(f"OK - {len(files)} yaml files parsed")
PY
' -- "$ROOT" || true

# 5. Secret-pattern scan over tracked files
run_check "secret scan" bash -c '
cd "$1" &&
PATTERNS="BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY|AIza[0-9A-Za-z_-]{35}|sk-[a-zA-Z0-9]{48}"
if git grep -nE "$PATTERNS" -- . ; then
    exit 1
fi
' -- "$ROOT" || true

TOTAL=${#SUMMARY[@]}
FAIL=$((TOTAL - PASS))

echo
echo "=== CI QA Summary ==="
for line in "${SUMMARY[@]}"; do
    echo "$line"
done
echo "=== $PASS/$TOTAL passed ==="

[ "$PASS" -eq "$TOTAL" ]
