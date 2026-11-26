#!/bin/bash
# devin-session-end.sh — SessionEnd hook that finalizes a Devin session:
# commits any remaining code changes and adds a close note to NotebookLM.

set -euo pipefail

export DEVIN_ARCHIVE_NOTEBOOK="${DEVIN_ARCHIVE_NOTEBOOK:-009b3efe-ff58-40bc-9a3b-9ec946b38deb}"

PAYLOAD_FILE=$(mktemp)
trap 'rm -f "$PAYLOAD_FILE"' EXIT
cat > "$PAYLOAD_FILE"

python3 - "$PAYLOAD_FILE" <<'PY'
import json, os, pathlib, subprocess, sys

PAYLOAD_FILE = sys.argv[1]
ARCHIVE = os.environ.get('DEVIN_ARCHIVE_NOTEBOOK', '009b3efe-ff58-40bc-9a3b-9ec946b38deb')
PROJECT_DIR = os.environ.get('DEVIN_PROJECT_DIR', os.getcwd())
PROJECT_NAME = pathlib.Path(PROJECT_DIR).name or 'this project'
MEMORY_FILE = pathlib.Path.home() / '.local/share/devin/notebook-summaries/session-memory.md'

def append_to_memory(title, body):
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f'\n---\n\n## {title}\n\n{body}\n')
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
        print('session-end hook: memory cache update failed:', e, file=sys.stderr)

try:
    with open(PAYLOAD_FILE, 'r', encoding='utf-8') as f:
        payload = json.load(f)
except Exception:
    payload = {}

session_id = payload.get('session_id', 'unknown')
reason = payload.get('reason', 'unknown')

# Final git checkpoint for any uncommitted changes.
checkpoint_msg = None
try:
    cp = subprocess.run(
        ['bash', os.path.expanduser('~/.config/devin/scripts/devin-git-checkpoint.sh'), '', session_id],
        capture_output=True,
        text=True,
        timeout=120,
        encoding='utf-8',
        errors='replace'
    )
    if cp.returncode == 0:
        checkpoint_msg = cp.stdout.strip()
    else:
        print('session-end hook: git checkpoint error:', cp.stderr, file=sys.stderr)
except Exception as e:
    print('session-end hook: git checkpoint exception:', e, file=sys.stderr)

# Build a close note for the archive.
close_note = f"Session {session_id} for `{PROJECT_NAME}` ended (reason: {reason})."
if checkpoint_msg:
    close_note += f"\nGit checkpoint: {checkpoint_msg}"

# Add the close note to NotebookLM (best-effort).
try:
    subprocess.run(
        ['nlm', 'source', 'add', ARCHIVE,
         '--text', close_note,
         '--title', f'Session end {session_id}',
         '--wait', '--json'],
        capture_output=True,
        text=True,
        timeout=120,
        encoding='utf-8',
        errors='replace',
        check=False
    )
except Exception as e:
    print('session-end hook: nlm archive error:', e, file=sys.stderr)

append_to_memory(f'Session end {session_id}', close_note)

# Hot-tier audit trail: record the session end, tagged kind:lifecycle so
# feed/context readers fold it structurally instead of regexing the text.
try:
    re_script = pathlib.Path(PROJECT_DIR) / 'scripts/chaba/recent-event.py'
    if re_script.exists():
        subprocess.run(
            ['python3', str(re_script),
             '--text', f'session ended ({reason})',
             '--ref', f'devin-session:{session_id}',
             '--kind', 'lifecycle'],
            capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace', check=False
        )
except Exception as e:
    print('session-end hook: recent-event error:', e, file=sys.stderr)

# Capture-router event (Phase C.3, OPS-1356): emit a focus_session router
# event so the knowledge-capture pipeline sees the session boundary. The
# emitter is dry-run only — events.jsonl/audit.jsonl under
# ~/.local/share/chaba/capture, deduped by dedupe_key, never a canonical
# sink write (gated writes stay behind capture-apply.py). Open items pinned
# via immediate-pin.py ride along as --open-ask so they reach the router.
# Best-effort but loud: failures print to stderr, never silently pass.
try:
    ce_script = pathlib.Path(PROJECT_DIR) / 'scripts/chaba/capture-event.py'
    if ce_script.exists():
        cmd = ['python3', str(ce_script),
               '--type', 'focus_session', '--source', 'devin',
               '--session', str(session_id),
               '--actor', 'devin-session-end-hook',
               '--summary', f'Session {session_id} ended (reason: {reason}).',
               '--ref', f'devin-session:{session_id}']
        pin_info = {}
        try:
            import yaml as _yaml
            imm = pathlib.Path.home() / '.local/share/chaba/immediate.yml'
            if imm.exists():
                imm_doc = _yaml.safe_load(imm.read_text(encoding='utf-8')) or {}
                for e in imm_doc.get('entries') or []:
                    if isinstance(e, dict) and e.get('session') == session_id:
                        pin_info = e
                        break
        except Exception as pin_exc:
            print('session-end hook: immediate-pin read failed:', pin_exc,
                  file=sys.stderr)
        payload = {'reason': reason, 'hook': 'devin-session-end.sh'}
        if checkpoint_msg:
            payload['git_checkpoint'] = checkpoint_msg[:300]
        for k in ('task', 'next', 'branch', 'last_commit'):
            if pin_info.get(k):
                payload[k] = pin_info[k]
        if pin_info.get('open'):
            payload['open'] = [str(o)[:300] for o in pin_info['open'][:10]]
            for item in payload['open'][:5]:
                cmd += ['--open-ask', f'{item} -> devin']
        cmd += ['--payload-json', json.dumps(payload, ensure_ascii=False)]
        ce = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                            encoding='utf-8', errors='replace', check=False)
        if ce.returncode != 0:
            print('session-end hook: capture-event rc=%s: %s'
                  % (ce.returncode, (ce.stderr or ce.stdout).strip()[:300]),
                  file=sys.stderr)
except Exception as e:
    print('session-end hook: capture-event error:', e, file=sys.stderr)

# Surface a concise finish message to the agent.
parts = [f"Session ended ({reason})."]
if checkpoint_msg:
    parts.append(f"Git checkpoint: {checkpoint_msg}")
parts.append("To shrink sessions.db, exit Devin and run: bash /home/tony/.config/devin/scripts/vacuum-devin-db.sh")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionEnd",
        "additionalContext": "\n".join(parts)
    }
}))

sys.exit(0)
PY
