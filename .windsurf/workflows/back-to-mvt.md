---
description: Back To Most Valuable Task (MVT)
---

Use this workflow whenever you notice you context-switched and the current task is left half-done.

0. Priority
  high:
  - When asked to create an item, infer and fill fields from the request; if unknown, ask a single clarifying question.
  - When you need confirmation, ask explicitly and block progress until answered.
  - Keep Google Sheets boolean fields compatible with checkbox semantics.
  - When writing to logs/memo sheets, include a short serial/trace identifier so we can reference entries.
  - If Sheets logs are involved, stabilize them FIRST:
    - Ensure `JARVIS_SHEETS_LOGS_ENABLED=true` and `JARVIS_SHEETS_LOGS_SHEET_NAME=<tab>` are present in the running container (redeploy if needed).
    - Verify `/jarvis/logs/sheets/status` shows `enabled=true`, non-empty `sheet_name`, and `queue_len` decreases after a test append.
    - Do not proceed to other tasks while `sheet_name` is empty or `queue_len` monotonically increases.

1. Restate the current objective (one sentence)
   - Write: "MVT: <single sentence outcome>".
   - If you can't say it in one sentence, split it into 2-3 outcomes and pick the most urgent one.

2. Rebuild context in 90 seconds
   - Read the last 30-80 lines of the most relevant logs (backend or CI), and the last 20 chat messages.
   - Write 3 bullets:
     - "What is failing right now?"
     - "What changed last?"
     - "What is the next verification step?"

3. Define the smallest next action (SNA)
  - Must be doable in <= 10 minutes.
  - Must produce a binary result (pass/fail, present/missing, connected/disconnected).
  - Format:
    - "SNA: <action>"
    - "Success looks like: <observable>"
    - "If fail, I will inspect: <1 place>"

   If the current issue is Sheets logs:
   - Prefer an SNA that checks *effective config* first:
     - `GET /jarvis/logs/sheets/status` then fix env/redeploy until `sheet_name` is non-empty.

   If the SNA involves pushing code:
   - If push fails with non-fast-forward:
     - If you have local uncommitted changes:
       - `git stash push -m "wip: pre-rebase"`
     - `git fetch origin`
     - `git rebase origin/<branch>`
     - resolve conflicts (if any)
     - If you stashed:
       - `git stash pop` (resolve conflicts if any)
     - push again

4. Execute SNA
   - Do only the SNA. No refactors, no docs, no extras.
   - Capture the output (copy/paste the key lines).

4.1. GitHub Actions watcher (start/stop; default stop)
   - If the SNA involves deploy/CI verification, use the GitHub Actions watcher:
     - Start watching (manual): `/jarvis/github/actions/watch/start`
     - Verify it is running: `/jarvis/github/actions/watch/list`
     - Stop watching (default state after SNA): `/jarvis/github/actions/watch/stop`
   - Always stop the watcher at the end of the SNA unless you explicitly decide to keep it running.

4.1.1. Auto-disable after build finished
   - When you observe the terminal/UI message `CI completed: ...`, stop the watcher immediately:
     - `/jarvis/github/actions/watch/stop`
   - If the build fails and you need to retry, you can start it again with `/jarvis/github/actions/watch/start`.

4.2. Persist result into memory (optional but preferred)
   - If the SNA produced a clear result (e.g., run conclusion + URL), store it as a memory item:
     - Key example: `runtime.github_actions.watch.latest`
     - Value example: `branch=<branch> conclusion=<conclusion> url=<url> sha=<sha>`
   - This requires `memory.write.enabled=true` in the system sheet.

4.5. Commit-only checkpoint (NO PUSH)
   - If you changed code or docs while executing the SNA:
     - Commit locally (e.g., `git add -A` then `git commit -m "..."`).
     - Do NOT push in this workflow.
   - To deploy / trigger CI, you must push manually after the workflow by running `git push` yourself.

5. Update the queue (WIP limit = 1)
   - Put exactly 1 item as "in progress".
   - Convert everything else into:
     - "Next" (max 3 items)
     - "Waiting" (blocked by other people/systems)
     - "Later" (nice-to-have)
   - Delete or merge duplicates.

6. Update the Back-to-MVT doc (every run)
   - Edit: `services/assistance/docs/BACK_TO_MVT.md`
   - Add a single row to the Run log table with:
     - Date/Time
     - MVT (one sentence)
     - SNA (one action)
     - Outcome (success/fail)
     - What improved (one sentence)

6.1. Persist result into memo items (optional)
   - If the run outcome should be remembered operationally, append a memo item (no UI required):
     - `POST /jarvis/memo/add` (requires `memo.enabled=true`)
     - Template (adjust host/token):
       - `curl -sS -X POST http://<host>/jarvis/memo/add -H 'content-type: application/json' -H 'X-Api-Token: <token>' -d '{"memo":"MVT=<...> SNA=<...> outcome=<success|fail> next=<...>","group":"ops","subject":"back-to-mvt"}'`

7. Self-assess (workflow improvement loop)
   - Score 0-2 for each:
     - Clarity (do I know what to do next?)
     - Confidence (do I believe it will work?)
     - Containment (did I avoid side-quests?)
   - If any score is 0:
     - Add ONE guardrail for next time (example: "No new tasks until SNA done").
   - Write one sentence:
     - "Next time, I will <process change>."

8. Close the loop
   - If SNA succeeded:
     - Pick the next SNA (repeat from step 3).
   - If SNA failed:
     - Write the failure hypothesis and the single best next inspection.

Notes:
- If you find yourself tempted to switch tasks, pause and run this workflow again.
- Keep a running "Decision log" in 3 lines max: Date, decision, why.
