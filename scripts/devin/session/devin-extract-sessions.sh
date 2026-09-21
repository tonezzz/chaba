#!/bin/bash
# devin-extract-sessions.sh — Extract Devin session transcripts to NotebookLM.
#
# Unlike devin-archive-sessions.sh, this does NOT summarise; it uploads a
# bounded raw transcript so the content can be queried directly in NotebookLM.
#
# Usage:
#   bash devin-extract-sessions.sh <session-id>
#   bash devin-extract-sessions.sh --older-than 3
#   bash devin-extract-sessions.sh --older-than 3 --delete

set -euo pipefail

export DEVIN_ARCHIVE_NOTEBOOK="${DEVIN_ARCHIVE_NOTEBOOK:-009b3efe-ff58-40bc-9a3b-9ec946b38deb}"
export SUMMARY_DIR="${DEVIN_SUMMARY_DIR:-$HOME/.local/share/devin/notebook-summaries}"
export RAW_DIR="$SUMMARY_DIR/raw"
export MAX_SOURCE_CHARS="${MAX_SOURCE_CHARS:-100000}"
export DELETE="${DELETE:-0}"

SESSION_ID=""
OLDER_THAN=""

usage() {
  cat <<'EOF'
Usage: devin-extract-sessions.sh <session-id>
       devin-extract-sessions.sh --older-than <days> [--delete]

Options:
  --older-than N   Extract all sessions whose last activity is > N days ago
  --delete         Run `devin rm --force` (or sqlite3 fallback) on each session after a successful upload
  -h, --help       Show this help

Environment:
  DEVIN_ARCHIVE_NOTEBOOK  Destination notebook ID for raw transcripts
  SUMMARY_DIR             Base local directory (default ~/.local/share/devin/notebook-summaries)
  MAX_SOURCE_CHARS        Max characters to upload per session (default 100000)
  DELETE                  Same as --delete when set to 1
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --older-than)
      shift
      OLDER_THAN="$1"
      shift
      ;;
    --delete)
      DELETE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -n "$SESSION_ID" ]]; then
        echo "Error: only one session-id may be provided" >&2
        usage >&2
        exit 1
      fi
      SESSION_ID="$1"
      shift
      ;;
  esac
done

if [[ -z "$SESSION_ID" && -z "$OLDER_THAN" ]]; then
  usage >&2
  exit 1
fi

for cmd in nlm python3 sqlite3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: $cmd not found in PATH" >&2
    exit 1
  fi
done

mkdir -p "$RAW_DIR"

export SESSION_ID
export OLDER_THAN
export DELETE

python3 - <<'PY'
import json, os, pathlib, re, sqlite3, subprocess, sys, time

DB = os.path.expanduser('~/.local/share/devin/cli/sessions.db')
ARCHIVE_NOTEBOOK = os.environ['DEVIN_ARCHIVE_NOTEBOOK']
RAW_DIR = os.environ['RAW_DIR']
MAX_SOURCE_CHARS = int(os.environ['MAX_SOURCE_CHARS'])
DELETE_AFTER = os.environ.get('DELETE', '0') == '1'


def safe_name(title):
    return re.sub(r'[^a-zA-Z0-9_-]+', '-', (title or '').strip())[:80]


def nlm(*args, input_text=None, timeout=300):
    use_json = '--json' in args
    result = subprocess.run(
        ['nlm', *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding='utf-8',
        errors='replace'
    )
    if result.returncode != 0:
        print('nlm error:', result.args, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None
    if use_json:
        try:
            return json.loads(result.stdout)
        except Exception:
            print('nlm returned non-JSON:', result.stdout[:500], file=sys.stderr)
            return None
    return result.stdout


def delete_session(session_id):
    # Try `devin rm` first; if the CLI can't see the session, fall back to sqlite3.
    try:
        dr = subprocess.run(
            ['devin', 'rm', '--force', session_id],
            capture_output=True,
            text=True,
            timeout=120,
            encoding='utf-8',
            errors='replace'
        )
        if dr.returncode == 0:
            print(f'  Deleted session {session_id} via devin rm')
            return True
        else:
            print(f'  devin rm failed: {dr.stderr.strip()}', file=sys.stderr)
    except Exception as e:
        print(f'  devin rm exception: {e}', file=sys.stderr)

    try:
        conn = sqlite3.connect(DB)
        conn.execute('DELETE FROM message_nodes WHERE session_id=?', (session_id,))
        conn.execute('DELETE FROM tool_call_state WHERE session_id=?', (session_id,))
        conn.execute('DELETE FROM sessions WHERE id=?', (session_id,))
        conn.commit()
        conn.close()
        print(f'  Deleted session {session_id} via sqlite3')
        return True
    except Exception as e:
        print(f'  sqlite3 delete failed: {e}', file=sys.stderr)
        return False


def extract_one(session_id, conn):
    c = conn.cursor()
    c.execute('SELECT title, created_at, last_activity_at, working_directory FROM sessions WHERE id=?', (session_id,))
    row = c.fetchone()
    if not row:
        print(f'Session {session_id} not found; skipping')
        return False

    title, created_at, last_activity_at, working_directory = row
    title = title or 'Untitled'
    display_title = title[:120]
    print(f'\n=== Extracting {session_id}: {display_title} ===')

    c.execute(
        'SELECT node_id, chat_message FROM message_nodes '
        'WHERE session_id=? ORDER BY node_id',
        (session_id,)
    )

    messages = []
    for node_id, chat_message in c:
        try:
            obj = json.loads(chat_message)
            role = obj.get('role', 'unknown')
            content = obj.get('content', '')
        except Exception:
            role = 'raw'
            content = chat_message or ''
        if role not in ('user', 'assistant') or not content:
            continue
        # Trim individual oversize messages to keep the source usable
        if len(content) > 200000:
            content = content[:150000] + '\n\n[... content truncated for archive ...]\n'
        messages.append(f'### Message {node_id} ({role})\n\n{content}\n')

    if not messages:
        print(f'No usable user/assistant messages for {session_id}; skipping')
        return False

    # Take the tail; the end of a session usually has the outcome
    transcript = ''.join(messages)
    if len(transcript) > MAX_SOURCE_CHARS:
        transcript = transcript[-MAX_SOURCE_CHARS:]
        if '\n### Message ' in transcript and not transcript.startswith('### Message '):
            transcript = transcript[transcript.find('\n### Message ') + 1:]

    # Enrich the transcript with session metadata at the top
    full_text = (
        f'# Session {session_id}: {display_title}\n\n'
        f'- **Created:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(created_at))}\n'
        f'- **Last activity:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(last_activity_at))}\n'
        f'- **Workspace:** {working_directory}\n\n'
        f'---\n\n{transcript}'
    )

    # Save locally
    safe = safe_name(title)
    raw_file = pathlib.Path(RAW_DIR) / f'{session_id}--{safe}.md'
    with open(raw_file, 'w', encoding='utf-8') as f:
        f.write(full_text)
    print(f'  Saved: {raw_file}')

    # Upload to NotebookLM archive as a raw, queryable source
    source_title = f'Session {session_id} — {display_title}'
    add_resp = nlm(
        'source', 'add', ARCHIVE_NOTEBOOK,
        '--text', full_text,
        '--title', source_title,
        '--wait',
        '--json',
        timeout=300
    )
    if not add_resp or 'source_id' not in add_resp:
        print(f'  Warning: failed to add source to notebook {ARCHIVE_NOTEBOOK}: {add_resp}', file=sys.stderr)
        return False

    print(f'  Added to notebook {ARCHIVE_NOTEBOOK} as source {add_resp["source_id"]}')

    if DELETE_AFTER:
        delete_session(session_id)

    return True


def extract_old(days):
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    threshold = int(time.time()) - days * 86400
    c = conn.cursor()
    c.execute(
        'SELECT id FROM sessions WHERE last_activity_at < ? AND hidden=0 ORDER BY last_activity_at ASC',
        (threshold,)
    )
    ids = [r[0] for r in c.fetchall()]
    conn.close()

    print(f'Found {len(ids)} sessions older than {days} day(s)')
    extracted = 0
    deleted = 0
    for sid in ids:
        conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
        if extract_one(sid, conn):
            extracted += 1
        conn.close()
    print(f'\nExtracted {extracted}/{len(ids)} sessions to NotebookLM')
    if DELETE_AFTER:
        print(f'Deletion was attempted for successfully extracted sessions')


def main():
    session_id = os.environ.get('SESSION_ID', '').strip()
    older_than = os.environ.get('OLDER_THAN', '').strip()

    if session_id:
        conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
        extract_one(session_id, conn)
        conn.close()
    elif older_than:
        extract_old(int(older_than))
    else:
        print('No session or --older-than value', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
PY
