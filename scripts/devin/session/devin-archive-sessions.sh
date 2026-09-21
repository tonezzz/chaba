#!/bin/bash
# devin-archive-sessions.sh — Archive old Devin sessions to NotebookLM summaries.
#
# Strategy:
# 1. For each session older than the retention threshold, extract the final
#    ~MAX_SOURCE_CHARS of user/assistant messages.
# 2. Stage that text in a temporary NotebookLM notebook.
# 3. Ask NotebookLM to produce a structured summary.
# 4. Save the summary locally and add it to the main archive notebook.
# 5. Delete the temporary staging notebook (raw chunks are not kept).
# 6. Optionally delete the original Devin session with `devin rm`.
#
# The live DB will shrink later when you run `vacuum-devin-db.sh`.
# Full raw DB backups should live on GDrive as the cold restore point.
#
# Usage:
#   bash devin-archive-sessions.sh <session-id>
#   bash devin-archive-sessions.sh --older-than 3
#   bash devin-archive-sessions.sh --older-than 3 --delete

set -euo pipefail

export DEVIN_ARCHIVE_NOTEBOOK="${DEVIN_ARCHIVE_NOTEBOOK:-009b3efe-ff58-40bc-9a3b-9ec946b38deb}"
export SUMMARY_DIR="${DEVIN_SUMMARY_DIR:-$HOME/.local/share/devin/notebook-summaries}"
export MAX_SOURCE_CHARS="${MAX_SOURCE_CHARS:-100000}"
export DELETE="${DELETE:-0}"

SESSION_ID=""
OLDER_THAN=""

usage() {
  cat <<'EOF'
Usage: devin-archive-sessions.sh <session-id>
       devin-archive-sessions.sh --older-than <days> [--delete]

Options:
  --older-than N   Archive all sessions whose last activity is > N days ago
  --delete         Run `devin rm` (or sqlite3 fallback) on each archived session
  -h, --help       Show this help

Environment:
  DEVIN_ARCHIVE_NOTEBOOK  Destination notebook ID for summaries
  SUMMARY_DIR             Local directory for saved summary .md files
  MAX_SOURCE_CHARS        Max characters to stage per session (default 100000)
  DELETE                  Same as --delete when set to 1

Example:
  bash devin-archive-sessions.sh --older-than 3 --delete
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

mkdir -p "$SUMMARY_DIR"

export SESSION_ID
export OLDER_THAN
export DELETE

python3 - <<'PY'
import json, os, pathlib, re, sqlite3, subprocess, sys, time

DB = os.path.expanduser('~/.local/share/devin/cli/sessions.db')
ARCHIVE_NOTEBOOK = os.environ['DEVIN_ARCHIVE_NOTEBOOK']
SUMMARY_DIR = os.environ['SUMMARY_DIR']
MAX_SOURCE_CHARS = int(os.environ['MAX_SOURCE_CHARS'])
DELETE_AFTER = os.environ.get('DELETE', '0') == '1'
PROMPT = os.environ.get(
    'SUMMARY_PROMPT',
    'Summarize this Devin session in a structured way that another Devin session can use as context. Include: 1) the original goal, 2) key files and commands used, 3) important decisions or design choices, 4) any problems and how they were fixed, 5) the final outcome. Be concise but include specific paths, version numbers, and command examples where relevant. Output Markdown.'
)


def safe_name(title):
    return re.sub(r'[^a-zA-Z0-9_-]+', '-', (title or '').strip())[:80]


def nlm(*args, input_text=None, timeout=300):
    """Run nlm and return the parsed JSON if --json is in the args."""
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


def archive_one(session_id, conn):
    c = conn.cursor()
    c.execute('SELECT title, created_at, last_activity_at, working_directory FROM sessions WHERE id=?', (session_id,))
    row = c.fetchone()
    if not row:
        print(f'Session {session_id} not found; skipping')
        return False

    title, created_at, last_activity_at, working_directory = row
    title = title or 'Untitled'
    display_title = title[:120]
    print(f'\n=== Archiving {session_id}: {display_title} ===')

    # Build a filtered transcript (user + assistant only, skip system/tool noise)
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
        # Some assistant contents are enormous tool dumps; trim obvious monolithic code blocks but keep the rest
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
        # Try to start on a message boundary
        if '\n### Message ' in transcript and not transcript.startswith('### Message '):
            transcript = transcript[transcript.find('\n### Message ') + 1:]

    # Staging notebook
    staging_title = f'staging-{session_id}'
    staging_resp = nlm('notebook', 'create', staging_title, '--json')
    if not staging_resp or 'notebook_id' not in staging_resp:
        print(f'Failed to create staging notebook for {session_id}', file=sys.stderr)
        return False
    staging_id = staging_resp['notebook_id']
    print(f'  Staging notebook: {staging_id}')

    try:
        # Add the tail as a text source
        source_title = f'{safe_name(title)}-{session_id}'
        add_resp = nlm(
            'source', 'add', staging_id,
            '--text', transcript,
            '--title', source_title,
            '--wait',
            '--json'
        )
        if not add_resp or 'source_id' not in add_resp:
            print(f'  Warning: failed to add source to staging: {add_resp}', file=sys.stderr)
            return False

        # Query for summary
        query_resp = nlm(
            'query', 'notebook', staging_id, PROMPT,
            '--new-conversation', '--json', timeout=180
        )
        if not query_resp or 'answer' not in query_resp:
            print(f'  Warning: summary query failed: {query_resp}', file=sys.stderr)
            return False

        summary = query_resp['answer']

        # Save locally
        safe = safe_name(title)
        summary_file = pathlib.Path(SUMMARY_DIR) / f'{session_id}--{safe}.md'
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(f'# Summary: {display_title}\n\n')
            f.write(f'- **Session ID:** {session_id}\n')
            f.write(f'- **Created:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(created_at))}\n')
            f.write(f'- **Last activity:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(last_activity_at))}\n')
            f.write(f'- **Workspace:** {working_directory}\n\n')
            f.write(summary)
        print(f'  Saved: {summary_file}')

        # Add summary to the main archive notebook
        add_summary_resp = nlm(
            'source', 'add', ARCHIVE_NOTEBOOK,
            '--text', summary,
            '--title', f'Summary: {display_title}',
            '--wait', '--json'
        )
        if not add_summary_resp or 'source_id' not in add_summary_resp:
            print(f'  Warning: failed to add summary to archive notebook', file=sys.stderr)
        else:
            print(f'  Added summary to archive notebook {ARCHIVE_NOTEBOOK}')

        # Delete the staging notebook to keep the cloud clean
        nlm('notebook', 'delete', staging_id, '--confirm')
        print(f'  Deleted staging notebook')

    except Exception as e:
        print(f'  Error archiving {session_id}: {e}', file=sys.stderr)
        # Try to clean up staging
        try:
            nlm('notebook', 'delete', staging_id, '--confirm')
        except Exception:
            pass
        return False

    if DELETE_AFTER:
        print(f'  Deleting session {session_id} from Devin')
        deleted = False
        result = subprocess.run(
            ['devin', 'rm', '--force', session_id],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f'    devin rm succeeded')
            deleted = True
        else:
            print(f'    devin rm failed: {result.stderr.strip()}', file=sys.stderr)

        if not deleted:
            try:
                conn = sqlite3.connect(DB)
                conn.execute('DELETE FROM message_nodes WHERE session_id=?', (session_id,))
                conn.execute('DELETE FROM tool_call_state WHERE session_id=?', (session_id,))
                conn.execute('DELETE FROM sessions WHERE id=?', (session_id,))
                conn.commit()
                conn.close()
                print(f'    Deleted session {session_id} via sqlite3')
                deleted = True
            except Exception as e:
                print(f'    sqlite3 delete failed: {e}', file=sys.stderr)

        if not deleted:
            return False

    return True


def archive_old(days):
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
    archived = 0
    for sid in ids:
        # Reopen connection per session to avoid holding a long-lived read
        conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
        if archive_one(sid, conn):
            archived += 1
        conn.close()
    print(f'\nArchived {archived}/{len(ids)} sessions')
    if DELETE_AFTER:
        print('Note: run the vacuum-devin-db.sh script after the next Devin restart to reclaim disk space.')


def main():
    session_id = os.environ.get('SESSION_ID', '').strip()
    older_than = os.environ.get('OLDER_THAN', '').strip()

    if session_id:
        conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
        archive_one(session_id, conn)
        conn.close()
    elif older_than:
        archive_old(int(older_than))
    else:
        print('No session or --older-than value', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
PY
