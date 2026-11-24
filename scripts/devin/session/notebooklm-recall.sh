#!/bin/bash
# notebooklm-recall.sh — SessionStart hook that injects a fast, local memory
# summary into the session context. NotebookLM remains the cold archive; this
# script only reads a small rolling cache built by PostCompaction/SessionEnd.
#
# Hybrid recall (card distiller-enrich-productionize): after the rolling
# session-memory tail, appends session_recall.py output — T1 mddb semantic
# search over the enriched devin-session/* bank + T2 FTS5 keyword search
# over local transcript .md archives. Both lanes fail open; the sibling
# script must be deployed next to this one (~/.config/devin/scripts/).

set -euo pipefail

export DEVIN_ARCHIVE_NOTEBOOK="${DEVIN_ARCHIVE_NOTEBOOK:-009b3efe-ff58-40bc-9a3b-9ec946b38deb}"
export RECALL_HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

PAYLOAD_FILE=$(mktemp)
trap 'rm -f "$PAYLOAD_FILE"' EXIT
cat > "$PAYLOAD_FILE"

python3 - "$PAYLOAD_FILE" <<'PY'
import json, os, pathlib, subprocess, sys

PAYLOAD_FILE = sys.argv[1]
PROJECT_DIR = os.environ.get('DEVIN_PROJECT_DIR', os.getcwd())
PROJECT_NAME = pathlib.Path(PROJECT_DIR).name or 'this project'
MEMORY_FILE = pathlib.Path.home() / '.local/share/devin/notebook-summaries/session-memory.md'
RECALL_SCRIPT = os.path.join(os.environ.get('RECALL_HOOK_DIR', ''),
                             'session_recall.py')

try:
    with open(PAYLOAD_FILE, 'r', encoding='utf-8') as f:
        payload = json.load(f)
except Exception:
    payload = {}

session_id = payload.get('session_id', '')

parts = []

if MEMORY_FILE.exists():
    try:
        text = MEMORY_FILE.read_text(encoding='utf-8', errors='replace')
        # Take the most recent ~3,500 chars — the hybrid block below gets
        # the larger share; together they must stay <=8KB injected.
        recent = text[-3500:] if len(text) > 3500 else text
        parts.append(
            f"# Recent session memory for `{PROJECT_NAME}`\n\n"
            f"{recent.strip()}"
        )
    except Exception as e:
        print('recall: could not read memory cache:', e, file=sys.stderr)

# Hybrid T1/T2 recall — bounded, fail-open (session_recall.py exits 0
# even when mddb or the index is unavailable).
if os.path.exists(RECALL_SCRIPT):
    try:
        out = subprocess.run(
            ['python3', RECALL_SCRIPT,
             '--session', session_id or '',
             '--project', PROJECT_NAME,
             '--max-chars', '4300'],
            capture_output=True, text=True, timeout=90)
        hybrid = (out.stdout or '').strip()
        if hybrid:
            parts.append(hybrid)
        if out.stderr.strip():
            print('recall: session_recall:', out.stderr.strip()[:400],
                  file=sys.stderr)
    except Exception as e:
        print('recall: hybrid recall failed:', e, file=sys.stderr)

if parts:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts)
        }
    }
    print(json.dumps(output))
PY
