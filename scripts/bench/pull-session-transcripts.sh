#!/usr/bin/env bash
# pull-session-transcripts.sh — copy the bench-recall fixture sessions'
# transcripts out of a REMOTE host's sessions.db into the local corpus
# sidecar, so bench-recall.py can run on a runner that doesn't own them.
#
# Usage:
#   scripts/bench/pull-session-transcripts.sh <host> [fixture.json]
# Defaults: fixture = fixtures/bench-recall-fixtures.json
#           output  = reports/bench-recall-corpus/transcripts.json
#           (or --corpus / BENCH_CORPUS on the bench)
set -euo pipefail
HOST="${1:?usage: pull-session-transcripts.sh <host> [fixture.json]}"
FIXTURE="${2:-$(dirname "$0")/../../fixtures/bench-recall-fixtures.json}"
OUT="$(dirname "$0")/../../reports/bench-recall-corpus/transcripts.json"
mkdir -p "$(dirname "$OUT")"

NAMES=$(python3 -c "import json;print(json.dumps([s['name'] for s in json.load(open('$FIXTURE'))['sessions']]))")

scp -o BatchMode=yes -q - "$HOST:/tmp/bench_extract.py" <<'PY'
import json, os, sqlite3, sys
DB = os.path.expanduser('~/.local/share/devin/cli/sessions.db')
names = json.loads(sys.argv[1])
db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
out = {}
for name in names:
    rows = db.execute('select chat_message from message_nodes '
                      'where session_id=? order by node_id', (name,)).fetchall()
    parts, raw = [], 0
    for (cm,) in rows:
        raw += len(cm)
        try:
            m = json.loads(cm)
        except Exception:
            continue
        role, meta = m.get('role'), m.get('metadata') or {}
        if role == 'assistant' or (
                role == 'user' and meta.get('is_user_input') in (1, True)):
            c = m.get('content')
            if isinstance(c, str) and c.strip():
                parts.append(f'### {role}\n{c[:8000]}')
    text = '\n\n'.join(parts)
    if len(text) > 600_000:
        half = 300_000
        text = text[:half] + '\n\n[...middle truncated...]\n\n' + text[-half:]
    title = db.execute('select title from sessions where id=?', (name,)).fetchone()
    out[name] = {'text': text, 'raw_bytes': raw,
                 'title': title[0] if title else None}
print(json.dumps(out))
PY

ssh -o BatchMode=yes "$HOST" "python3 /tmp/bench_extract.py '$NAMES'" > "$OUT"
python3 -c "import json;d=json.load(open('$OUT'));print(f'wrote $OUT: {len(d)} transcripts')"
