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
   - **Session-capture sweep (mandatory, per `ssot.knowledge-capture.yml` / `session-capture` procedure):**
     route every unmet/unfinished request or follow-up to a durable sink (card/request/comment via board-api, focus-inbox, lesson, KB/SSOT promotion, or pointer note) and record where filed;
     save/update deduped pointer notes for non-obvious discoveries; file retainable/educate-me answers as lessons (`scripts/lesson-add.py` or `/lesson`, state if write fails);
     attach outcomes/evidence to cards/reports (reusable deltas only). Where available, `scripts/chaba/immediate-pin.py` and `scripts/chaba/recent-event.py` may record resume/events, but they do not replace durable sinks or the handoff packet.

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

6b. Report linkage (CMS)
   - For every card this session closed or advanced, confirm its `links:`
     names the right report node (e.g. chaba-nest for Nest program work)
     and that a `comms:` line records the outcome — that is what keeps the
     CMS report structure updated; the generators read cards.json on their
     own cadence, so a card without links/comms is invisible to reports.
   - If the work produced a report artifact, note the doc key/page in comms.

6c. Artifact landing sweep (gate — do not skip)
   - Enumerate every artifact this session produced: reports, analyses,
     benchmark outputs, job results, datasets, generated files.
   - For each, verify it landed in a durable home — CMS page (reports/
     analyses, per cms-report standard), card comms (card outcomes), repo
     file (code/docs), focus-inbox (parked ideas) — NOT chat-only, NOT /tmp
     or a runtime that dies with the session.
   - If any artifact has no durable home, land it now (publish the CMS page,
     write the comms, park the inbox entry) before reporting close.
   - In the close report, list artifacts and where each landed so the user
     can audit the sweep.

7. Park unfinished work in the kanban inbox
   - Anything still pending at close — deferred subtasks, follow-ups, "would be nice"
     items — must not die in the summary. File it in `docs/ssot/focus-inbox/` per the
     save-to-focus convention: one `<UTC-timestamp>-<slug>.yml` per coherent topic,
     `status: draft`, following `TEMPLATE.yml` (or route to a card/request via board-api when actionable).
   - Prefer one inbox file with a `subtasks:` list over many tiny files.
   - Items deliberately dropped or already tracked elsewhere don't need parking.
   - Tell the user what was parked; the next active session triages it from the inbox.

7b. Session Handoff Packet (required, when closing/handing off/pausing)
   - Produce and save a **Session Handoff Packet** per `docs/ssot/ssot.knowledge-capture.yml` (OpenChamber project knowledge note preferred and/or card comms refs): `objective`, `as_of`, `current_state` (done|in progress|blocked, evidence refs), `canonical_refs`, `open_asks_decisions` (each routed to a durable sink with owner/options/default), `next_action`, `where_filed` (**mandatory**: `item -> sink/ID/path`), `notes` (risks/gaps/refresh; label state `canonical(served)` / `branch/unmerged` / `live runtime` when relevant).
   - If live external state outlives the session (Colab runtime awaiting UI, staged job manifest, in-flight dispatch, warm cache), the handoff must include: staged/live now (paths/manifest/state), exact next action incl. UI-only steps, what survives vs dies, and subtasks per unfinished lane. A focus-inbox handoff entry (`tags: [handoff]`, `*-handoff.yml` or equivalent) may complement the packet with operational detail.
   - Push is implied for handoffs consumed by another session/host — use `scripts/git-safe-push.sh` on satellite checkouts. State that can't be pushed gets its resume recipe written into the packet/entry.

8. Push (only if asked — except handoff entries/packets consumed by another session/host, which must be pushed)
   - Push to `origin` for the current branch only when the user explicitly asks for it
     ('push', 'push/etc.', or similar).
   - Report the remote tracking status.

9. Close
   - Report final status, commit hash(es), anything the pre-close sweep surfaced
     (running dispatches, open requests, dirty live checkout), and the **`where_filed`** list from the Session Handoff Packet (no chat-only outcomes).
   - End with 'Session closed.'

Edge cases

- If the working tree is dirty with unrelated changes, still follow the trigger but do not
  include unrelated work unless the user explicitly says "everything".
- If the user asks for a close but nothing is ready to commit, just say 'Session closed.'
- If the session involved learning, also create or update a `ssot.learning.*` file so the
  lessons are preserved.
