#!/bin/bash
# devin-chunked-extract.sh — Chunk a Devin session, upload chunks to a staging
# NotebookLM notebook, ask NotebookLM to summarize the chunks, save the summary
# to the main archive, then delete the staging notebook (and the session if
# requested).
#
# This maximizes captured history by uploading multiple chunks per session.
# The raw chunks live briefly in a staging notebook; only the final summary is
# kept in the archive.
#
# Usage:
#   bash devin-chunked-extract.sh <session-id>
#   bash devin-chunked-extract.sh <session-id> --delete
#   MAX_SOURCE_CHARS=3000 bash devin-chunked-extract.sh rust-patella

set -euo pipefail

export DEVIN_ARCHIVE_NOTEBOOK="${DEVIN_ARCHIVE_NOTEBOOK:-009b3efe-ff58-40bc-9a3b-9ec946b38deb}"
export SUMMARY_DIR="${DEVIN_SUMMARY_DIR:-$HOME/.local/share/devin/notebook-summaries}"
export RAW_DIR="$SUMMARY_DIR/raw"
export MAX_SOURCE_CHARS="${MAX_SOURCE_CHARS:-100000}"
export MAX_MESSAGE_TRUNC="${MAX_MESSAGE_TRUNC:-100000}"
export MAX_CHUNKS="${MAX_CHUNKS:-20}"
export DELETE="${DELETE:-0}"

SESSION_ID=""

usage() {
  cat <<'EOF'
Usage: devin-chunked-extract.sh <session-id> [--delete]

Options:
  --delete    Run `devin rm --force` (or sqlite3 fallback) on the session after archiving.

Environment:
  DEVIN_ARCHIVE_NOTEBOOK  Destination notebook ID for the final summary.
  MAX_SOURCE_CHARS        Max characters per chunk (default 100000).
  MAX_CHUNKS              Max chunks to upload per session (default 20).
  DELETE                  Set to 1 to delete the session.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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
        exit 1
      fi
      SESSION_ID="$1"
      shift
      ;;
  esac
done

if [[ -z "$SESSION_ID" ]]; then
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
export DELETE

python3 - <<'PY'
import json, os, pathlib, re, shlex, sqlite3, subprocess, sys, time

DB = os.path.expanduser('~/.local/share/devin/cli/sessions.db')
ARCHIVE_NOTEBOOK = os.environ['DEVIN_ARCHIVE_NOTEBOOK']
RAW_DIR = os.environ['RAW_DIR']
MAX_SOURCE_CHARS = int(os.environ['MAX_SOURCE_CHARS'])
MAX_MESSAGE_TRUNC = int(os.environ['MAX_MESSAGE_TRUNC'])
MAX_CHUNKS = int(os.environ['MAX_CHUNKS'])
DELETE_AFTER = os.environ.get('DELETE', '0') == '1'
PROMPT = os.environ.get(
    'SUMMARY_PROMPT',
    'Summarize this Devin session in a structured way that another Devin session can use as context. Include: 1) the original goal, 2) key files and commands used, 3) important decisions or design choices, 4) any problems and how they were fixed, 5) the final outcome. Be concise but include specific paths, version numbers, and command examples where relevant. Output Markdown.'
)


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
        if result.stdout:
            print('nlm stdout:', result.stdout[:1000], file=sys.stderr)
        if result.stderr:
            print('nlm stderr:', result.stderr[:1000], file=sys.stderr)
        return None
    if use_json:
        try:
            return json.loads(result.stdout)
        except Exception:
            print('nlm returned non-JSON:', result.stdout[:500], file=sys.stderr)
            return None
    return result.stdout


def nlm_source_add_file(notebook_id, text, title, timeout=300):
    # Avoid the 128k single-argument limit of the nlm wrapper by sending the
    # text through ssh stdin and using nlm's --file option inside the container.
    nlm_host = os.environ.get('NLM_HOST', 'mn01')
    inner = (
        f"cat > /tmp/nlm_upload.txt && "
        f"nlm source add {shlex.quote(notebook_id)} "
        f"--file /tmp/nlm_upload.txt "
        f"--title {shlex.quote(title)} --wait --json"
    )
    cmd = [
        'ssh', '-o', 'BatchMode=yes', nlm_host,
        f'podman exec -i notebooklm-mcp sh -c {shlex.quote(inner)}'
    ]
    result = subprocess.run(
        cmd,
        input=text,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding='utf-8',
        errors='replace'
    )
    if result.returncode != 0:
        print('nlm source add error:', cmd, file=sys.stderr)
        if result.stdout:
            print('nlm stdout:', result.stdout[:1000], file=sys.stderr)
        if result.stderr:
            print('nlm stderr:', result.stderr[:1000], file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except Exception:
        print('nlm source add returned non-JSON:', result.stdout[:500], file=sys.stderr)
        return None


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


def main():
    session_id = os.environ['SESSION_ID']
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    c = conn.cursor()
    c.execute('SELECT title, created_at, last_activity_at, working_directory FROM sessions WHERE id=?', (session_id,))
    row = c.fetchone()
    if not row:
        print(f'Session {session_id} not found; skipping')
        conn.close()
        sys.exit(1)

    title, created_at, last_activity_at, working_directory = row
    title = title or 'Untitled'
    display_title = title[:120]
    print(f'\n=== Chunked archive for {session_id}: {display_title} ===')

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
        if len(content) > MAX_MESSAGE_TRUNC:
            content = content[:MAX_MESSAGE_TRUNC] + '\n\n[... content truncated for archive ...]\n'
        messages.append(f'### Message {node_id} ({role})\n\n{content}\n')

    if not messages:
        print(f'No usable user/assistant messages for {session_id}; skipping')
        conn.close()
        sys.exit(1)

    header = (
        f'# Session {session_id}: {display_title}\n\n'
        f'- **Created:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(created_at))}\n'
        f'- **Last activity:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(last_activity_at))}\n'
        f'- **Workspace:** {working_directory}\n\n'
        f'---\n\n'
    )

    # Build chunks that respect message boundaries
    chunks = []
    current = []
    current_len = 0
    for m in messages:
        if current and current_len + len(m) > MAX_SOURCE_CHARS:
            chunks.append(''.join(current))
            current = []
            current_len = 0
        current.append(m)
        current_len += len(m)
    if current:
        chunks.append(''.join(current))

    chunks = chunks[:MAX_CHUNKS]
    print(f'  {len(messages)} messages -> {len(chunks)} chunk(s) (max {MAX_CHUNKS})')

    # Save full transcript locally (all chunks, no cap)
    safe = safe_name(title)
    full_file = pathlib.Path(RAW_DIR) / f'{session_id}--{safe}--full.md'
    with open(full_file, 'w', encoding='utf-8') as f:
        f.write(header)
        for chunk in chunks:
            f.write(chunk)
    print(f'  Saved full transcript: {full_file}')

    # Create a staging notebook for the raw chunks
    staging_title = f'staging-{session_id}'
    staging_resp = nlm('notebook', 'create', staging_title, '--json', timeout=300)
    if not staging_resp or 'notebook_id' not in staging_resp:
        print(f'Failed to create staging notebook for {session_id}', file=sys.stderr)
        sys.exit(1)
    staging_id = staging_resp['notebook_id']
    print(f'  Staging notebook: {staging_id}')

    failures = []
    try:
        source_ids = []
        failed_chunks = 0
        for i, chunk in enumerate(chunks, start=1):
            if i == 1:
                chunk_text = header + chunk
                chunk_title = f'{session_id} — {display_title} (chunk {i}/{len(chunks)})'
            else:
                chunk_text = (
                    f'# Session {session_id}: {display_title} (continued, chunk {i}/{len(chunks)})\n\n'
                    f'---\n\n{chunk}'
                )
                chunk_title = f'{session_id} — {display_title} (chunk {i}/{len(chunks)})'

            add_resp = nlm_source_add_file(
                staging_id,
                chunk_text,
                chunk_title,
                timeout=300
            )
            if not add_resp or 'source_id' not in add_resp:
                print(f'  Warning: chunk {i} upload failed: {add_resp}', file=sys.stderr)
                failed_chunks += 1
                continue
            source_ids.append(add_resp['source_id'])
            print(f'    Uploaded chunk {i}/{len(chunks)} as {add_resp["source_id"]}')

        if not source_ids:
            print('  No chunks uploaded; aborting', file=sys.stderr)
            sys.exit(1)
        if failed_chunks:
            failures.append(f'{failed_chunks}/{len(chunks)} chunk uploads failed')

        # Summarize the chunks
        print('  Querying NotebookLM for a summary...')
        query_resp = nlm(
            'query', 'notebook', staging_id, PROMPT,
            '--new-conversation', '--json',
            timeout=300
        )
        summary_ok = bool(query_resp and 'answer' in query_resp)
        if not summary_ok:
            print(f'  Warning: summary query failed: {query_resp}', file=sys.stderr)
            failures.append('summary query failed')
            summary = f'No summary could be generated for session {session_id} (NotebookLM query failed).'
        else:
            summary = query_resp['answer']

        # Save summary locally
        summary_file = pathlib.Path(RAW_DIR) / f'{session_id}--{safe}--summary.md'
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(f'# Summary: {display_title}\n\n')
            f.write(f'- **Session ID:** {session_id}\n')
            f.write(f'- **Created:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(created_at))}\n')
            f.write(f'- **Last activity:** {time.strftime("%Y-%m-%d %H:%M", time.gmtime(last_activity_at))}\n')
            f.write(f'- **Workspace:** {working_directory}\n')
            f.write(f'- **Chunks archived:** {len(source_ids)}\n\n')
            if not summary_ok:
                f.write('**Note:** the NotebookLM summary query failed; this is a metadata stub, not a real summary.\n\n')
            f.write(summary)
        print(f'  Saved: {summary_file}')

        # Add the summary to the main archive
        add_summary_resp = nlm_source_add_file(
            ARCHIVE_NOTEBOOK,
            summary,
            f'Summary: {display_title} ({session_id})',
            timeout=300
        )
        if not add_summary_resp or 'source_id' not in add_summary_resp:
            print(f'  Warning: failed to add summary to archive: {add_summary_resp}', file=sys.stderr)
            failures.append('summary not added to archive')
        else:
            print(f'  Added summary to archive as {add_summary_resp["source_id"]}')

    finally:
        # Delete the staging notebook, which removes all temporary chunk sources
        del_resp = nlm('notebook', 'delete', staging_id, '--confirm', timeout=300)
        if del_resp is None:
            print(f'  Warning: failed to delete staging notebook {staging_id} '
                  f'— remove manually: nlm notebook delete {staging_id} --confirm', file=sys.stderr)
            failures.append(f'staging notebook {staging_id} not deleted')
        else:
            print(f'  Deleted staging notebook {staging_id}')

    if DELETE_AFTER:
        if failures:
            print(f'  Skipping --delete for {session_id}: archive incomplete ({"; ".join(failures)})', file=sys.stderr)
        elif not delete_session(session_id):
            failures.append('session delete failed')

    conn.close()
    if failures:
        print(f'\nIncomplete: {session_id} — ' + '; '.join(failures))
        sys.exit(1)
    print(f'\nDone: {session_id}')


if __name__ == '__main__':
    main()
PY
