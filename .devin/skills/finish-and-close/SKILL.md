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
     'what have we learnt? how can we improve?'
   - Aliases: 'finish', 'close', 'wrap up', 'wrap it up', 'close this out', 'end session',
     'close session', 'session complete', 'we are done', 'done for now', 'that is all'.
   - Normalize extra whitespace and punctuation; match intent, not exact text.

2. Summarize and review
   - Summarize what was done, what is pending, and any errors or surprises.
   - If the user asks 'what have we learnt? how can we improve?', capture the lessons
     into a learning SSOT under `docs/ssot/` (e.g. `ssot.learning.session-close.2026.yml`).

3. Validate
   - Run `node scripts/ssot-validate-all.mjs`.
   - If SSOT files changed, ensure validation passes. Fix YAML errors before committing.

4. Commit
   - `git status --short` to confirm the intended files are included.
   - Use `git add` for specific files or `git add -A` when the user says "everything".
   - Commit with a generated message if the user did not supply one.
   - If the pre-commit hook blocks due to SSOT bloat warnings and splitting is not practical
     for the session, use `git commit --no-verify` and tell the user the reason.

5. Catch leftovers
   - After commit, run `git status --short` again. If anything remains, do a second focused
     commit automatically or warn the user.

6. Push (only if asked)
   - Push to `origin` for the current branch only when the user explicitly asks for it
     ('push', 'push/etc.', or similar).
   - Report the remote tracking status.

7. Close
   - Report final status and commit hash(es).
   - End with 'Session closed.'

Edge cases
- If the working tree is dirty with unrelated changes, still follow the trigger but do not
  include unrelated work unless the user explicitly says "everything".
- If the user asks for a close but nothing is ready to commit, just say 'Session closed.'
- If the session involved learning, also create or update a `ssot.learning.*` file so the
  lessons are preserved.
