# Action (Operator Playbook)

## Now (what to do next)
- **Most valuable next action (10 minutes):** Record a deploy/build snapshot (health + status + CI) and append it to memo, so you can compare after the next push/redeploy.
- **Then:** If you push a new change, rerun the snapshot and confirm:
  - `git_sha` / `image_tag` changed (if configured)
  - CI run SHA matches what you expect
  - Containers remain healthy

## Preflight: confirm you’re using the latest ACTION.md
Run this before taking actions if you had multiple chats open or you suspect drift.

### Repo sync (local)
1. `git status -sb`
2. `git fetch origin`
3. Confirm branch is up to date:
   - `git rev-parse HEAD`
   - `git rev-parse origin/idc1-assistance`
   - If different: `git rebase origin/idc1-assistance`
4. Confirm `services/assistance/docs/ACTION.md` is not stale:
   - `git log -n 1 -- services/assistance/docs/ACTION.md`

### Deploy sync (optional)
- Check latest CI SHA for `idc1-assistance`:
  - `GET /github/actions/latest?owner=tonezzz&repo=chaba&branch=idc1-assistance`
- If you just pushed, confirm `head_sha` equals your latest commit SHA.

## Overview (quick context)
- **What this is:** The single file you and I use to stay aligned, pick the next Most Valuable Task, and run verification steps without losing context.
- **Current objective:** GitHub Actions watcher integration for Jarvis (manual trigger only), plus reliable observability + persistence (UI log + memo/memory where appropriate).
- **Target repo/branch:** `tonezzz/chaba` / `idc1-assistance`
- **Deployed base URL:** `https://assistance.idc1.surf-thailand.com/jarvis/api`
- **Key health/version endpoints:**
  - `GET /health` (includes `build.git_sha` / `build.image_tag` when configured)
  - `GET /status` (includes uptime + optional container list)
- **Key CI endpoints:**
  - `GET /github/actions/latest?owner=tonezzz&repo=chaba&branch=idc1-assistance`
  - `GET /github/actions/watch?...` (bounded wait-until-completed)
- **Key watcher endpoints:**
  - `POST /github/actions/watch/start`
  - `GET /github/actions/watch/list`
  - `POST /github/actions/watch/stop`

## Policy: avoid redundant docs
- **Single source of truth:** `services/assistance/docs/ACTION.md` is the authoritative operator playbook.
- **Keep other docs short:** Other docs should link here instead of duplicating procedures.
- **When you notice duplication:**
  - Move the *canonical* procedure/checklist into `ACTION.md`.
  - Replace the duplicated content elsewhere with a short pointer to the relevant `ACTION.md` section.

## How to use this file
- **Command format**
  - Ask me: `Read ACTION.md and execute: <section>`
  - Examples:
    - `Read ACTION.md and execute: Current MVT loop`
    - `Read ACTION.md and execute: SNA for GitHub Actions watcher`
    - `Read ACTION.md and execute: Verification checklist (deployed)`
- **Shortcut**
  - If you say: `action`
    - I will run: **Now (what to do next)**
    - Output: snapshot summary + memo text (and I will append the memo if allowed)

## Guardrails (read first)
- **WIP limit = 1**
  - Only one in-progress task at a time.
- **No side quests until SNA is done**
  - If you feel context-switching, run **Current MVT loop**.
- **Always stop watchers after the SNA**
  - Default end-state: watcher stopped (unless explicitly continuing).
- **Prefer binary checks**
  - Every SNA must yield a pass/fail observable.

## Guardrail: avoid multi-chat file conflicts
Use this anytime you have multiple chats/agents editing the repo.

### Policy (single writer)
- Only **one chat** is allowed to modify files at a time.
- All other chats may:
  - read files
  - suggest edits
  - run verification calls
  - but must **not** apply patches/commits

### Lightweight lock (recommended)
- Before editing, write a memo “lock” so other chats can see it:
  - `POST /jarvis/memo/add` with:
    - `subject=repo-lock`
    - `group=ops`
    - `memo="lock repo=chaba branch=idc1-assistance owner=<name> ts=<iso> expires_in_min=30"`
- After push, append an “unlock” memo:
  - `memo="unlock repo=chaba branch=idc1-assistance ts=<iso>"`

### Conflict prevention checklist (before you edit)
1. `git status -sb` (must be clean or intentionally dirty)
2. If remote may have changed:
   - `git fetch origin`
   - `git rebase origin/idc1-assistance`
3. Make changes
4. Run tests (or a targeted check)
5. Commit
6. `git push`
7. Re-run deploy snapshot (Now)

## Immediate fix: memo/logs not updating
Use this when you “don’t see memo/logs update” after a run.

### Memo (does memo append work?)
1. **Check effective memo config**
   - `GET /jarvis/debug/memo`
   - Success looks like:
     - `feature_enabled=true`
     - `memo_enabled=true`
     - non-empty `spreadsheet_id` and `sheet_name`
     - `header_error=null`
2. **Append a test memo**
   - `POST /jarvis/memo/add`
   - Success looks like:
     - response contains `ok=true` and `appended=1`
3. **If you still can’t “see it”**
   - Confirm you are looking at the correct Google Sheet tab (`sheet_name` from debug output).
   - If you use a UI that reads memo, it may be cached; refresh/reload.

### Sheets logs (is the log writer actually flushing?)
1. **Check sheets logs status**
   - `GET /jarvis/logs/sheets/status`
   - Watch these fields:
     - `enabled`
     - `sheet_name` (must be non-empty)
     - `queue_len` (should go down after appends)
     - `server_enabled` (if false, queue may not flush)
2. **If `queue_len` increases or stays > 0**
   - Treat as config drift: logs are enabled but background flusher isn’t running.
   - Fix by making the running container’s env effective (redeploy if needed):
     - `JARVIS_SHEETS_LOGS_ENABLED=true`
     - `JARVIS_SHEETS_LOGS_SHEET_NAME=<tab>`
     - `JARVIS_SHEETS_LOGS_SPREADSHEET_ID=<id>` (if required by your deployment)
   - Then re-check `/jarvis/logs/sheets/status` until `queue_len` drains.

## Verify counts: memo rows + memory items loaded
Use this when Jarvis says things like: “I have **7 memory items loaded**” or when you want to confirm memo actually appended.

### Proposal: `sheet_item_count` tool (recommended)
Goal: a single, stable way to answer “how many items are in sheet X?” without relying on UI caching or ad-hoc parsing.

- **Better name:** `sheet_row_count` (more precise) or `sheet_item_count` (OK if we define “item” clearly).
- **Where to implement (preferred):** Jarvis backend endpoint + optional Jarvis tool wrapper.
  - Endpoint: `GET /jarvis/debug/sheet_row_count?spreadsheet_id=<id>&sheet=<tab>&has_header=true`
  - Returns:
    - `ok`
    - `spreadsheet_id`, `sheet`
    - `rows_total`
    - `rows_excluding_header`
    - `error` (if any)
- **Why an endpoint (not only an MCP tool):**
  - It works even when the front-end is cached.
  - It can reuse existing Sheets auth inside the running container.
  - It can be protected by `_require_api_token_if_configured`.
- **How we’ll use it (when deployed):**
  - Memo rows:
    - `GET /jarvis/debug/sheet_row_count?sheet=memo&has_header=true`
  - Logs rows:
    - `GET /jarvis/debug/sheet_row_count?sheet=logs&has_header=true`

### Check counts (single call)
- `GET /jarvis/debug/counts`
- Expected fields:
  - `memory.count` (number of enabled memory items loaded)
  - `memory.cached_count` (may be 0 if not preloaded yet)
  - `memo.rows` (number of memo rows excluding header)
  - `memo.sheet` / `memo.spreadsheet_id` (where it wrote)

### If `/jarvis/debug/counts` is 404
- This usually means the deployed container hasn’t picked up the latest code yet.
- Fallback checks:
  1. **Memory count (backend prewarm)**
     - `GET /status`
     - Use: `startup_prewarm.memory_n` (this is the last prewarm load count; may be 0 if prewarm is disabled or didn’t load memory).
  2. **Memo “count” confirmation (append evidence)**
     - `POST /jarvis/memo/add`
     - Confirm the response contains `ok=true` and an `updatedRange` like `memo!A27:K27`.
       - The row number (e.g. `27`) is a quick proxy for “memo rows exist and are increasing”.

### Interpret
- **If `memory.count` is lower than expected**
  - Some memory items may be disabled or the memory sheet failed to load.
  - Next check: `GET /status` → `startup_prewarm.ok` and consider reloading memory via the normal Jarvis flow.
- **If `memo.rows` increases but you don’t see it**
  - You’re likely looking at the wrong tab or a cached UI view; use `memo.sheet` from the response.

## Current MVT loop (based on @[/back-to-mvt])
### 1) Restate the objective (one sentence)
- **MVT:** Validate the deployed GitHub Actions watcher end-to-end (start, observe, auto-stop, persist latest result).

### 2) Rebuild context in 90 seconds
- **What is failing right now?**
  - Unknown until verified on deployed backend.
- **What changed last?**
  - Watcher start endpoint fixed (stop_on_completed/max_runtime_seconds), watcher loop has auto-stop + timeout, UI log persistence, header-aware sheet upserts + tests.
- **Next verification step?**
  - Run the deployed verification SNA below and observe state + logs.

### 3) Define the Smallest Next Action (SNA)
- **SNA:** Start the watcher on the deployed backend for the target repo/branch, then verify it transitions to stopped when CI completes (or times out), and confirm `latest` + UI log updated.
- **Success looks like:**
  - `/jarvis/github/actions/watch/start` returns 200
  - `/jarvis/github/actions/watch/list` shows `running=true`
  - After CI completes: watcher stops automatically (`running=false`, `stopped_reason=completed`) OR times out with `stopped_reason=timeout`
  - `/jarvis/github/actions/watch` reflects newest run and status
  - UI log contains `run_detected` and `run_completed` (and possibly `watch_timeout` if timeout)
- **If fail, inspect:**
  - `jarvis-backend` logs around watcher loop and `/watch/start` handler

### 4) Execute SNA (do only the SNA)
- Follow: **SNA for GitHub Actions watcher**

### 5) Update the queue (WIP limit = 1)
- Keep exactly one “in progress” item.
- Convert everything else to:
  - Next (max 3)
  - Waiting
  - Later

### 6) Persist the outcome (preferred)
- **Back-to-MVT run log**
  - Add one row in `services/assistance/docs/BACK_TO_MVT.md`.
- **Optional: memo append (ops)**
  - Append a memo with the result so it’s discoverable later.
- **Ask Jarvis to append a run memo (preferred)**
  - After each ACTION.md run (each SNA attempt), ask Jarvis to append a memo that records:
    - MVT
    - SNA
    - outcome (success/fail)
    - next action
  - Prompt template:
    - `Append a memo: subject=back-to-mvt group=ops memo="MVT=<...> SNA=<...> outcome=<success|fail> next=<...>" then summarize in 3 lines.`

## SNA for GitHub Actions watcher (deployed)
### Inputs you must decide (fill before running)
- **Base URL:** `https://assistance.idc1.surf-thailand.com/jarvis/api`
- **Repo:** `tonezzz/chaba`
- **Branch:** `idc1-assistance`
- **Event:** optional (e.g. `push`, `pull_request`)
- **Poll seconds:** default is fine unless debugging
- **Stop on completed:** `true`
- **Max runtime seconds:** e.g. `900` (15m)

## Deploy/Build status awareness (save current state)
### Goal
- Be able to answer:
  - “What version is deployed right now?”
  - “Is the backend healthy?”
  - “What’s the current CI run status for this branch?”
  - “Did the deploy actually update?”

### Snapshot deployed backend state (binary)
1. **Health (fast)**
   - `GET /health`
   - Success looks like:
     - `ok=true`
     - `build.git_sha` is present (if configured)
     - `build.image_tag` is present (if configured)
2. **Status (richer)**
   - `GET /status`
   - Capture:
     - `instance_id`, `hostname`, `uptime_s`
     - `startup_prewarm.ok`
     - `containers` (if present)

### Snapshot CI/build status (GitHub)
- **Latest run (single fetch)**
  - `GET /github/actions/latest?owner=tonezzz&repo=chaba&branch=idc1-assistance`
- **Wait-until-completed (blocking poll, bounded)**
  - `GET /github/actions/watch?owner=tonezzz&repo=chaba&branch=idc1-assistance&poll_seconds=10&timeout_seconds=600`
- **Background watcher (push notifications + UI log, recommended while deploying)**
  - Start: `POST /github/actions/watch/start`
  - List: `GET /github/actions/watch/list`
  - Stop: `POST /github/actions/watch/stop`

### Persist the snapshot (optional but preferred)
- If you want “what was deployed” recorded for later comparison, append a memo:
  - Subject: `deploy-snapshot`
  - Group: `ops`
  - Memo template:
    - `deploy_snapshot ts=<iso> env=idc1-assistance git_sha=<sha> image_tag=<tag> instance_id=<id> uptime_s=<n> ci_status=<status> ci_conclusion=<conclusion> ci_url=<url>`

### Ask Jarvis to do it (snapshot + memo + summary)
- You can ask Jarvis (the deployed assistant) to:
  - Fetch `/health` + `/status`
  - Fetch `/github/actions/latest` (for `tonezzz/chaba` / `idc1-assistance`)
  - Append a memo entry (`subject=deploy-snapshot`, `group=ops`)
  - Return a short human summary you can paste back into this chat
- Prompt template (edit as needed):
  - `Run Deploy/Build status awareness now. Capture health/status + latest CI for tonezzz/chaba idc1-assistance. Append a memo deploy_snapshot with ts, git_sha, image_tag, instance_id, uptime, ci_status/conclusion/url, then summarize in 6 lines max.`

### Steps
1. **Start watcher**
   - Call: `POST /github/actions/watch/start`
2. **Confirm running**
   - Call: `GET /github/actions/watch/list`
3. **Wait for completion**
   - Watch for “CI completed …” notification or poll:
     - `GET /github/actions/watch`
4. **Confirm auto-stop**
   - `GET /github/actions/watch/list` should show:
     - `running=false`
     - `stopped_reason=completed` (or `timeout`)
5. **Stop manually if needed**
   - Call: `POST /github/actions/watch/stop`

### Observability checklist
- **State**
  - `watch/list` includes the key you started, with `running`, `ts`, `stopped_reason`.
- **Latest**
  - `watch` returns the latest known run payload.
- **UI log**
  - Confirm the daily UI log includes entries with kinds:
    - `run_detected`
    - `run_completed`
    - `watch_error` (only if error)
    - `watch_timeout` (only if max-runtime hit)

## Unified context (what matters)
### GitHub Actions watcher integration
- **Triggering rule**
  - Must be manual (voice command or REST), not automatic unless explicitly configured.
- **Core endpoints**
  - `POST /github/actions/watch/start`
  - `POST /github/actions/watch/stop`
  - `GET /github/actions/watch/list`
  - `GET /github/actions/watch`
  - `GET /github/actions/latest`
- **Stop behavior**
  - Auto-stop when completed if `stop_on_completed=true`.
  - Auto-stop when runtime exceeds `max_runtime_seconds`.

### Memory + System sheet upserts (header-aware)
- **Invariant: created_at is preserved**
  - Never overwrite a non-empty `created_at`.
- **Invariant: updated_at is always refreshed**
  - RFC3339 UTC (ends with `Z`).
- **Invariant: do not clobber unrelated columns**
  - Only set the mapped columns for the record.

### Memo append (ops breadcrumbs)
- Used to persist short operational outcomes you want to recover later.
- Endpoint: `POST /jarvis/memo/add` (requires `memo.enabled=true`)

## Important warnings
- **If you see repeated 500s on start**
  - Treat as config drift or deploy mismatch; inspect effective container version + logs.
- **If watcher never stops**
  - Confirm:
    - `stop_on_completed=true`
    - `max_runtime_seconds` is set to a sane bound
  - Then manually stop and inspect watcher loop logs.
- **If logs/memo/sheets are involved**
  - Stabilize logs/sheets first (effective config, status endpoints), then proceed.

## Decision log (keep to 3 lines max)
- `<date>`: `<decision>` — `<why>`

## Improvements (pair-working backlog)
### How to use
- Add items here during work (from you or me).
- Ask me: `Read ACTION.md and process: Improvements`.
  - I will:
    - Convert repeated pain into a guardrail/checklist/SNA update.
    - Keep changes small and actionable.
    - Mark items as processed.

### Template
- **[new] <short title>**
  - **Signal:** <what happened / what you noticed>
  - **Impact:** <why it hurt>
  - **Change:** <what to add/change in this playbook>
  - **Owner:** <you|me>
  - **Status:** <new|in_progress|processed>

### Items
- **[new]**
  - **Signal:**
  - **Impact:**
  - **Change:**
  - **Owner:**
  - **Status:** new