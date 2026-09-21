#!/bin/bash
# notebooklm-compaction.sh — PostCompaction hook that archives the compactor
# summary to NotebookLM so long sessions leave a searchable trace.
#
# The devin compactor already replaces old conversation in the model's context
# with this summary. This script simply saves that summary to the archive.

set -euo pipefail

export DEVIN_ARCHIVE_NOTEBOOK="${DEVIN_ARCHIVE_NOTEBOOK:-009b3efe-ff58-40bc-9a3b-9ec946b38deb}"

# Save the hook payload (stdin) to a temp file so the Python heredoc can read it.
PAYLOAD_FILE=$(mktemp)
trap 'rm -f "$PAYLOAD_FILE"' EXIT
cat > "$PAYLOAD_FILE"

python3 - "$PAYLOAD_FILE" <<'PY'
import json, os, pathlib, subprocess, sys, time

PAYLOAD_FILE = sys.argv[1]
ARCHIVE = os.environ.get('DEVIN_ARCHIVE_NOTEBOOK', '009b3efe-ff58-40bc-9a3b-9ec946b38deb')
SUMMARY_DIR = os.path.expanduser('~/.local/share/devin/notebook-summaries/compactions')
MEMORY_FILE = pathlib.Path.home() / '.local/share/devin/notebook-summaries/session-memory.md'

def append_to_memory(title, body):
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f'\n---\n\n## {title}\n\n{body}\n')
        # Roll the cache to ~50KB to keep start-up reads fast.
        try:
            text = MEMORY_FILE.read_text(encoding='utf-8')
            limit = 50000
            if len(text) > limit:
                trimmed = text[-limit:]
                cutoff = trimmed.find('\n## ')
                if cutoff > 0:
                    trimmed = trimmed[cutoff:]
                MEMORY_FILE.write_text(trimmed, encoding='utf-8')
        except Exception:
            pass
    except Exception as e:
        print('compaction hook: memory cache update failed:', e, file=sys.stderr)

try:
    with open(PAYLOAD_FILE, 'r', encoding='utf-8') as f:
        payload = json.load(f)
except Exception:
    print('compaction hook: could not parse stdin JSON', file=sys.stderr)
    sys.exit(0)

summary = payload.get('summary', '') or ''
if not summary:
    # Nothing to archive
    sys.exit(0)

session_id = payload.get('session_id', 'unknown')
timestamp = time.strftime('%Y%m%d-%H%M%S')

os.makedirs(SUMMARY_DIR, exist_ok=True)
summary_file = pathlib.Path(SUMMARY_DIR) / f'{session_id}-{timestamp}.md'

with open(summary_file, 'w', encoding='utf-8') as f:
    f.write(f'# Compaction summary for session {session_id}\n\n')
    f.write(summary)

print(f'compaction hook: saved {summary_file}', file=sys.stderr)

# Push to NotebookLM archive
result = subprocess.run(
    ['nlm', 'source', 'add', ARCHIVE,
     '--text', summary,
     '--title', f'Compaction summary {session_id}',
     '--wait', '--json'],
    capture_output=True,
    text=True,
    timeout=120,
    encoding='utf-8',
    errors='replace'
)

if result.returncode != 0:
    print('compaction hook: nlm source add failed:', result.stderr, file=sys.stderr)
    sys.exit(0)

try:
    data = json.loads(result.stdout)
    if 'source_id' in data:
        print(f'compaction hook: archived as source {data["source_id"]}', file=sys.stderr)
    else:
        print('compaction hook: nlm did not return source_id:', result.stdout, file=sys.stderr)
except Exception:
    print('compaction hook: nlm output:', result.stdout, file=sys.stderr)

append_to_memory(f'Compaction {session_id}', summary)

# Try to checkpoint any code changes that have accumulated since the last compaction.
checkpoint_msg = None
try:
    cp = subprocess.run(
        ['bash', os.path.expanduser('~/.config/devin/scripts/devin-git-checkpoint.sh'), str(summary_file), session_id],
        capture_output=True,
        text=True,
        timeout=120,
        encoding='utf-8',
        errors='replace'
    )
    if cp.returncode == 0:
        checkpoint_msg = cp.stdout.strip()
    else:
        print('compaction hook: git checkpoint error:', cp.stderr, file=sys.stderr)
except Exception as e:
    print('compaction hook: git checkpoint exception:', e, file=sys.stderr)

# Remind the user to reclaim disk at the next safe opportunity.
parts = [
    "Context compacted. To shrink sessions.db later, exit Devin and run: "
    "bash /home/tony/.config/devin/scripts/vacuum-devin-db.sh"
]
if checkpoint_msg:
    parts.append(f"Git checkpoint: {checkpoint_msg}")
additional_context = "\n".join(parts)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostCompaction",
        "additionalContext": additional_context
    }
}))
PY
