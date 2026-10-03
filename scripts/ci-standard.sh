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

# 3b. Jobs manifest must validate and render identically to committed units
run_check "jobs manifest render" bash -c "
  python3 '$ROOT/scripts/render-jobs.py' --check || exit 1
  if [ -d '$ROOT/systemd/generated' ]; then
    TMPGEN=\$(mktemp -d)
    python3 - \"\$TMPGEN\" '$ROOT' <<PY2 || exit 1
from pathlib import Path
import importlib.util, sys
out = Path(sys.argv[1]); root = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location('rj', root / 'scripts/render-jobs.py')
rj = importlib.util.module_from_spec(spec); spec.loader.exec_module(rj)
man = rj.load_manifest()
for host in man['config']['repo']:
    for name, body in rj.render_host(man, host).items():
        d = out / host; d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body)
gen = root / 'systemd/generated'
have = sorted(str(p.relative_to(gen)) for p in gen.rglob('*') if p.is_file())
want = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file())
if have != want:
    print('generated/ file-set drift:'); print(' only committed:', sorted(set(have)-set(want))); print(' only rendered:', sorted(set(want)-set(have))); sys.exit(1)
for rel in have:
    if (gen/rel).read_text() != (out/rel).read_text():
        print(f'generated/{rel} content drift — re-run render-jobs.py'); sys.exit(1)
print(f'OK - {len(have)} generated units in sync')
PY2
  fi
" || true

# 4. No tracked .env / secret-looking files (allow .env.example/.sample)
run_check "no tracked dotenv files" bash -c "
  DOTENV=$(git -C "$ROOT" ls-files | grep -E '\\.env$|\\.env\\.[^.]+$' | grep -vE '\\.env\\.(example|sample)$' || true)
  if [ -n \"$DOTENV\" ]; then
    echo \"$DOTENV\"
    exit 1
  fi
" || true

# 5. Flag untracked files older than 7 days that are outside the known
# allowlist. Fresh untracked files are treated as active WIP (parallel
# sessions write to this tree constantly) and only listed as a warning.
ALLOWED_UNTRACKED='^docs/kb/.*\.md$|^docs/ssot/focus-inbox/.*\.yml$|^mcp-servers/mcp-opennb/.*$|^scripts/ci-(smoke|standard|qa|all)\.sh$|^scripts/mddb/vector-reindex\.py$|^scripts/ops/yt-transcript\.sh$|^stacks/idc01/line-relay/.*$|^stacks/web/public/media/.*$'
MAX_AGE_DAYS=7
STALE=$(git -C "$ROOT" ls-files --others --exclude-standard -z |
    xargs -0 -I{} stat -c '%Y %n' "$ROOT/{}" 2>/dev/null |
    awk -v cutoff="$(date -d "-$MAX_AGE_DAYS days" +%s)" '$1 < cutoff {print $2}' |
    sort || true)
UNEXPECTED=$(echo "$STALE" | grep -Ev "$ALLOWED_UNTRACKED" || true)
FRESH=$(git -C "$ROOT" ls-files --others --exclude-standard -z |
    xargs -0 -I{} stat -c '%Y %n' "$ROOT/{}" 2>/dev/null |
    awk -v cutoff="$(date -d "-$MAX_AGE_DAYS days" +%s)" '$1 >= cutoff {print $2}' | sort || true)
if [ -n "$FRESH" ]; then
    echo "Fresh untracked (WIP, <$MAX_AGE_DAYS days — not failing):"
    echo "$FRESH"
fi
if [ -n "$UNEXPECTED" ]; then
    echo "Stale unexpected untracked files (>$MAX_AGE_DAYS days):"
    echo "$UNEXPECTED"
    SUMMARY+=("[FAIL] untracked file allowlist")
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
