# Action (Operator Playbook)

## Now (what to do next)
- **Most valuable next action (10 minutes):** Record a deploy/build snapshot (health + status + CI) and append it to memo, so you can compare after the next push/redeploy.
- **Then:** If you push a new change, rerun the snapshot and confirm:
  - `git_sha` / `image_tag` changed (if configured)
  - CI run SHA matches what you expect
  - Containers remain healthy

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

## Guardrails (read first)
- **WIP limit = 1**
  - Only one in-progress task at a time.
- **No side quests until SNA is done**
  - If you feel context-switching, run **Current MVT loop**.
- **Always stop watchers after the SNA**
  - Default end-state: watcher stopped (unless explicitly continuing).
- **Prefer binary checks**
  - Every SNA must yield a pass/fail observable.

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