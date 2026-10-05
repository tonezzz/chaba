---
name: finish-and-close
description: Session end workflow — summarize, capture learnings, commit/push, and close.
allowed-tools:
  - exec
  - grep
  - read
  - edit
  - write
  - find_file_by_name
  - todo_write
  - ask_user_question
  - mcp_call_tool
  - mcp_list_tools
triggers:
  - user
  - model
---

Standard workflow for ending a session when the user asks to finish/close.

1. Detect the trigger
   - Primary phrases: 'Let's finish and close', 'finish and close', 'session closed',
     'end session', 'close session', 'session complete', 'wrap up the session',
     'what have we learnt? how can we improve?'
   - The trigger must refer to ending the SESSION. Phrases about closing a card,
     a task, a PR, or an item of work ('close the card', 'finish the rename',
     'close this out' about a ticket) are NOT session-end triggers.
   - If the intent is ambiguous, ask before proceeding — never commit code on a
     misread cue.

2. Pre-close sweep (do this before committing anything)
   - `git worktree list` — report session worktrees that still need merge/removal.
   - Check in-flight work: cards with `action.status: running` or `queued` that this
     session dispatched, open `requests:` on touched cards — list them so nothing is
     orphaned mid-flight.
   - Check the live checkout (`chaba-tony-dell`) for dirty state if this session
     touched it — flag unsynced/uncommitted work instead of closing blind.
   - If the session pushed dashboard changes, run
     `scripts/home-assistant/sync-ssot-from-live.sh` and commit before closing.

3. Summarize and review
   - Summarize what was done, what is pending, and any errors or surprises.
   - If the user asks 'what have we learnt? how can we improve?', capture the lessons
     into a learning SSOT under `docs/ssot/` (e.g. `ssot.learning.session-close.2026.yml`).

4. Validate
   - Run `node scripts/ssot-validate-all.mjs`.
   - If SSOT files changed, ensure validation passes. Fix YAML errors before committing.

5. Commit
   - `git status --short` to confirm the intended files are included.
   - Use `git add` for specific files or `git add -A` when the user says "everything".
   - Commit with a generated message if the user did not supply one.
   - If a pre-commit hook blocks the commit, STOP and tell the user why — do not
     use `--no-verify` or otherwise bypass hooks.

6. Catch leftovers
   - After commit, run `git status --short` again. If anything remains, do a second focused
     commit automatically or warn the user.

7. Park unfinished work in the kanban inbox
   - Anything still pending at close — deferred subtasks, follow-ups, "would be nice"
     items — must not die in the summary. File it in `docs/ssot/focus-inbox/` per the
     save-to-focus convention: one `<UTC-timestamp>-<slug>.yml` per coherent topic,
     `status: draft`, following `TEMPLATE.yml`.
   - Prefer one inbox file with a `subtasks:` list over many tiny files.
   - Items deliberately dropped or already tracked elsewhere don't need parking.
   - Tell the user what was parked; the next active session triages it from the inbox.

8. Push (only if asked)
   - Push to `origin` for the current branch only when the user explicitly asks for it
     ('push', 'push/etc.', or similar).
   - Report the remote tracking status.

9. Close
   - Report final status, commit hash(es), and anything the pre-close sweep surfaced
     (running dispatches, open requests, dirty live checkout).
   - End with 'Session closed.'

Edge cases

- If the working tree is dirty with unrelated changes, still follow the trigger but do not
  include unrelated work unless the user explicitly says "everything".
- If the user asks for a close but nothing is ready to commit, just say 'Session closed.'
- If the session involved learning, also create or update a `ssot.learning.*` file so the
  lessons are preserved.
