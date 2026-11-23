#!/bin/bash
# notebooklm-recall.sh — SessionStart hook that injects a fast, local memory
# summary into the session context. NotebookLM remains the cold archive; this
# script only reads a small rolling cache built by PostCompaction/SessionEnd.
#
# Hybrid recall (card distiller-enrich-productionize / bench v2 91.7% hit@3):
# session_recall.py adds a T1 mddb semantic + T2 local FTS5 keyword block
# ahead of the flat session-memory.md tail. Fail-open: any error or timeout
# falls back to the tail-only behavior.

set -euo pipefail

export DEVIN_ARCHIVE_NOTEBOOK="${DEVIN_ARCHIVE_NOTEBOOK:-009b3efe-ff58-40bc-9a3b-9ec946b38deb}"

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
RECALL_PY=""
for cand in "$SELF_DIR/session_recall.py" \
            "$HOME/CascadeProjects/chaba/scripts/devin/session/session_recall.py"; do
  if [ -f "$cand" ]; then RECALL_PY="$cand"; break; fi
done

RECALL_BLOCK=""
if [ -n "$RECALL_PY" ]; then
  RECALL_BLOCK="$(timeout 20 python3 "$RECALL_PY" --hook-text 2>/dev/null || true)"
fi
export RECALL_BLOCK

PAYLOAD_FILE=$(mktemp)
trap 'rm -f "$PAYLOAD_FILE"' EXIT
cat > "$PAYLOAD_FILE"

python3 - "$PAYLOAD_FILE" <<'PY'
import json, os, pathlib, sys

PAYLOAD_FILE = sys.argv[1]
PROJECT_DIR = os.environ.get('DEVIN_PROJECT_DIR', os.getcwd())
PROJECT_NAME = pathlib.Path(PROJECT_DIR).name or 'this project'
MEMORY_FILE = pathlib.Path.home() / '.local/share/devin/notebook-summaries/session-memory.md'
RECALL_BLOCK = os.environ.get('RECALL_BLOCK', '').strip()

try:
    with open(PAYLOAD_FILE, 'r', encoding='utf-8') as f:
        payload = json.load(f)
except Exception:
    payload = {}

session_id = payload.get('session_id', '')

parts = []
if RECALL_BLOCK:
    parts.append(RECALL_BLOCK)

if MEMORY_FILE.exists():
    try:
        text = MEMORY_FILE.read_text(encoding='utf-8', errors='replace')
        # Take the most recent ~8,000 chars so the recall is concise.
        recent = text[-8000:] if len(text) > 8000 else text
        parts.append(
            f"# Recent session memory for `{PROJECT_NAME}`\n\n"
            f"{recent.strip()}"
        )
    except Exception as e:
        print('recall: could not read memory cache:', e, file=sys.stderr)

context = "\n\n".join(parts)[:16000] if parts else None

if context:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context
        }
    }
    print(json.dumps(output))
PY
