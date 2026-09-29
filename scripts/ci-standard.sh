#!/usr/bin/env bash
# Chaba standardization / repo-hygiene CI gate.
# Enforces: SSOT validity, memory-banks SSOT is renderable, service source
# paths in ssot.services.yml exist when they are repo-relative, no .env
# files are tracked, and no unexpected untracked files are present.
# Exit 0 if all checks pass.

set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUMMARY=()
PASS=0

run_check() {
    local name="$1"
    shift
    if "$@" >/tmp/ci-standard-last.out 2>&1; then
        SUMMARY+=("[PASS] $name")
        ((PASS++))
        return 0
    else
        SUMMARY+=("[FAIL] $name")
        cat /tmp/ci-standard-last.out
        return 1
    fi
}

# 1. SSOT structure validation
run_check "SSOT validation" node "$ROOT/scripts/ssot-validate-all.mjs" || true

# 2. Memory-bank registry SSOT must render to valid JSON
run_check "memory-banks render" bash -c "
  python3 '$ROOT/scripts/ada/render-memory-banks.py' --output /tmp/ci-memory-banks.json >/dev/null &&
  python3 -m json.tool /tmp/ci-memory-banks.json >/dev/null
" || true

# 3. Repo-relative source paths in ssot.services.yml must exist
run_check "service source path audit" bash -c '
python3 - "$1" "$2" <<\PY
import re
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1]).resolve()
path = Path(sys.argv[2]).resolve()

data = yaml.safe_load(path.read_text())
services = data.get("services", {})
missing = []
skipped = 0

def first_path(text):
    text = str(text or "").split("\n")[0].split(";")[0].strip()
    text = re.sub(r"\s*\(.*\)", "", text).strip()
    return text

for name, spec in services.items():
    status = str(spec.get("status") or "").lower()
    if "decommissioned" in status:
        continue
    src = first_path(spec.get("source", ""))
    if not src:
        continue
    if (
        src.startswith("~") or src.startswith("/") or src.startswith("http")
        or re.search(r"\$\{|`", src)
    ):
        skipped += 1
        continue
    target = (root / src).resolve()
    if not (
        target.exists()
        or target.with_suffix(".py").exists()
        or (root / (src + ".py")).exists()
    ):
        missing.append(f"  {name}: {src}")

if missing:
    print("Missing repo-relative source paths:")
    print("\n".join(missing))
    sys.exit(1)

print(f"OK - {len(services)} services checked, {len(missing)} missing, {skipped} host/absolute skipped")
PY
' -- "$ROOT" "$ROOT/docs/ssot/infrastructure/ssot.services.yml" || true

# 4. No tracked .env / secret-looking files (allow .env.example/.sample)
run_check "no tracked dotenv files" bash -c "
  DOTENV=$(git -C "$ROOT" ls-files | grep -E '\\.env$|\\.env\\.[^.]+$' | grep -vE '\\.env\\.(example|sample)$' || true)
  if [ -n \"$DOTENV\" ]; then
    echo \"$DOTENV\"
    exit 1
  fi
" || true

# 5. Flag untracked files that are outside the known allowlist
ALLOWED_UNTRACKED='^docs/kb/.*\.md$|^docs/ssot/apps/ssot\.apps\.ada-cms-reports\.yml$|^docs/ssot/focus-inbox/.*\.yml$|^scripts/ci-(smoke|standard)\.sh$|^scripts/ops/yt-transcript\.sh$|^stacks/web/public/media/.*$'
if ! UNTRACKED=$(git -C "$ROOT" ls-files --others --exclude-standard | sort); then
    UNTRACKED=""
fi
UNEXPECTED=$(echo "$UNTRACKED" | grep -Ev "$ALLOWED_UNTRACKED" || true)
if [ -n "$UNEXPECTED" ]; then
    echo "Unexpected untracked files:"
    echo "$UNEXPECTED"
    SUMMARY+=("[FAIL] untracked file allowlist")
    cat /tmp/ci-standard-last.out
else
    SUMMARY+=("[PASS] untracked file allowlist")
    PASS=$((PASS + 1))
fi

TOTAL=${#SUMMARY[@]}
FAIL=$((TOTAL - PASS))

echo
echo "=== CI Standard Summary ==="
for line in "${SUMMARY[@]}"; do
    echo "$line"
done
echo "=== $PASS/$TOTAL passed ==="

[ "$PASS" -eq "$TOTAL" ]
