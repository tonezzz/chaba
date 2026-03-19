# Action (Operator Playbook)

## Now (what to do next)

- **Most valuable next action (10 minutes):** `TODO-NOW-001` (see `services/assistance/docs/TODO.md#now`)

### 4 most valuable next actions (update this every time you run "Now")
1. **Deploy/build snapshot (10 minutes)**
   - Run: **Deploy/Build status awareness (save current state)**
   - Paste the results into the status chart below.
   - Append a memo (optional but preferred).
2. **Prove redeploy updated (10 minutes)**
   - If `/health` doesn’t include build identity, run: **Assess a pending job (might already be done)** then prove the running image digest via Portainer/host inspection.
3. **Watcher SNA (15 minutes)**
   - Run: **SNA for GitHub Actions watcher (deployed)**
   - Goal: verify start -> running -> completed/timeout -> auto-stop + UI log.

### Always-updated status chart (fill this every time you run “Now”)
| Item | Value |
| --- | --- |
| Need rebuild? | |
| Need redeploy? | |
| Health ok | |
| Status ok | |
| uptime_s | |
| Snapshot ts | |
| Deployed base URL | `https://assistance.idc1.surf-thailand.com/jarvis/api` |
| instance_id | |
| CI status | |
| CI conclusion | |
| CI head_sha | |
| CI updated_at | |
| CI url | |
| jarvis-backend image (tag) | |
| jarvis-backend image digest | |
| jarvis-backend image created | |
| Backend image published in latest CI? | |

Need redeploy? rule (binary):
- **Yes** if CI is `completed/success` AND either:
  - `jarvis-backend image created` is older than `CI updated_at`, OR
  - (once SHA tags are deployed) running image tag is not `...:sha-<CI head_sha>`
- Otherwise: **No/Unknown** (then run **Prove redeploy updated**).

Need rebuild? rule (binary, selective CI):
- **Yes** if the latest CI run is `completed/success` but the backend job did **not** publish a new backend image.
- In the publish workflow, this is usually visible as **`Build and push (CLI) = skipped`** for the backend matrix job.
- If you only redeploy without a new image being published, the container will restart on the same old digest.

### Current cautions (read before doing anything)
- If `build.git_sha` / `build.image_tag` are `null`, you cannot prove “new code is running” from `/health` alone.
- GitHub Actions publishes images selectively (only images whose inputs changed).
- Empty commits typically do not rebuild images anymore; to force a rebuild, change/touch a file inside the relevant service directory.
- WIP limit = 1: if you start a new thing, merge it into the existing checklist/backlog section (see **Intake/merge policy** below).

### Current pick
- `<pick 1>` — `<why now>` — `<next command/section to run>`

Update rule:
- After you run any ACTION.md procedure, always come back here and set **Current pick** to the *single* next move.

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

## Post-push status (do I need to redeploy?)
Run this after you `git push`.

### Inputs
- **Expected SHA (local):** `git rev-parse HEAD`

### Checks
1. **CI finished for the expected SHA**
   - `GET /github/actions/latest?owner=tonezzz&repo=chaba&branch=idc1-assistance`
   - Success looks like:
     - `run.status=completed`
     - `run.conclusion=success`
     - `run.head_sha == expected_sha`
2. **Deploy picked up the change (heuristics)**
   - `GET /status`
   - Signals of redeploy:
     - `instance_id` changed vs last snapshot
     - `uptime_s` is small (e.g. < 10 minutes)
3. **API surface sanity (detect deploy drift)**
   - `GET /openapi.json`
   - Confirm expected new endpoints exist (example):
     - `/debug/counts` or any newly-added route you care about

### Decision rule (notify me)
- **Redeploy required** if ANY are true:
  - CI is not green for `expected_sha`
  - `/openapi.json` does not contain the endpoints you expect from your latest push
  - `/status` shows long uptime and you expected a restart (likely didn’t redeploy)
- Otherwise, proceed to the next SNA.

## Overview (quick context)
- **What this is:** The single file you and I use to stay aligned, pick the next Most Valuable Task, and run verification steps without losing context.
- **Current objective:** GitHub Actions watcher integration for Jarvis (manual trigger only), plus reliable observability + persistence (UI log + memo/memory where appropriate).
- **Target repo/branch:** `tonezzz/chaba` / `idc1-assistance`
- **Deployed base URL:** `https://assistance.idc1.surf-thailand.com/jarvis/api`
- **Host (loopback) endpoints (effective on the Docker host running the stack):**
  - Backend health: `http://127.0.0.1:18018/health`
  - Frontend UI: `http://127.0.0.1:18080/jarvis/`
  - Deep-research-worker: `http://127.0.0.1:18030/health` (if exposed by the worker)
- **Host port binds (from `stacks/idc1-assistance/docker-compose.yml`):**
  - `127.0.0.1:18018` -> `jarvis-backend:8018`
  - `127.0.0.1:18080` -> Jarvis frontend container
  - `127.0.0.1:18030` -> `deep-research-worker:8030`
  - `127.0.0.1:3051` -> `mcp-bundle:3050`
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

## Policy: memo vs memory vs knowledge (what goes where)
- **Memo** (append-only inbox)
  - Use for breadcrumbs, handoffs, and human notes.
  - Expect it to grow; do not rely on it for “current status”.
- **Memory** (upsertable current-state KV)
  - Use for a single authoritative “latest status” value that should be kept updated.
  - Examples:
    - `runtime.deploy.snapshot.latest`
    - `runtime.github_actions.watch.latest`
- **Knowledge** (stable reference)
  - Use for durable concepts/procedures/architecture that should not churn.

## Policy: status memo should be updated, not appended
- Prefer an **upsert** key for status snapshots.
- **Preferred store:** Memory key `runtime.deploy.snapshot.latest`.
- **Fallback store (if memory upsert path is unavailable):** sys_kv key `runtime.deploy.snapshot.latest` via `POST /jarvis/sys_kv/set`.

Memory write gating:
- `POST /jarvis/memory/set` requires sys_kv key `memory.write.enabled=true`.

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
2. **If `memo_enabled=false` but you believe sys_kv is set**
   - `/jarvis/debug/memo` reads from a cached `sys_kv` snapshot.
   - Force a refresh by calling:
     - `POST /jarvis/memo/header/normalize`
   - Then re-check:
     - `GET /jarvis/debug/memo`
3. **Append a test memo**
   - `POST /jarvis/memo/add`
   - Success looks like:
     - response contains `ok=true` and `appended=1`
4. **If you still can’t “see it”**
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
  - Preferred: `/jarvis/github/actions/watch/list` includes the key you started (may be `running=true` briefly)
  - Fallback (bounded wait): `/jarvis/github/actions/watch?owner=...&repo=...&branch=...&timeout_seconds=...` returns `completed=true`
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

Notes (from `stacks/idc1-assistance/CONFIG.md`):
- Public WS URL is `wss://assistance.idc1.surf-thailand.com/jarvis/ws/live`.
- Backend serves WS internally at `/ws/live` (edge proxy must strip `/jarvis`).
- Hitting a WS URL as plain HTTP GET may return `404`; use a WS client.

### Assess a pending job (might already be done)
Use this when you think “the job is still running” but you suspect CI and/or redeploy already finished.

#### Binary checks
1. **Is CI already completed?**
   - Call: `GET /github/actions/latest?owner=tonezzz&repo=chaba&branch=idc1-assistance`
   - Pass if:
     - `run.status=completed`
     - and `run.updated_at` is recent (matches your last push time)
   - If `status=in_progress|queued`, CI is still running.
2. **Did the backend restart since that CI run?**
   - Call: `GET /status`
   - Compare:
     - `uptime_s` (lower means a more recent restart)
     - and `instance_id` (changes on restart)
   - Heuristic pass if:
     - `uptime_s` is less than ~1 hour AND your last redeploy was within that window.
3. **Are containers healthy?**
   - From `GET /status`, pass if key containers show `status=running` and `health=healthy` where available.

#### If CI completed but you can’t prove the deploy updated
If `GET /health` returns `build.git_sha=null` / `build.image_tag=null`, you cannot confirm “new code is running” from HTTP alone.

Preferred options:
- **Via Portainer/host inspection**
  - Check the running `jarvis-backend` container image reference/digest matches the image built for the CI `head_sha`.
- **Make /health authoritative (later)**
  - Plumb build identity into the container env and have the backend return it.

Build-to-deploy identity rule (preferred):
- GitHub Actions publishes immutable tags per image:
  - `:<branch>` (mutable)
  - `:sha-<full_git_sha>` (immutable)
  - `:sha-<short_git_sha>` (convenience)
- This allows a binary check: running container image tag should match the CI `head_sha`.

#### Portainer MCP (this repo)
This repo includes a local Portainer + Portainer MCP stack at `stacks/idc1-portainer/`.

Key references:
- `stacks/idc1-portainer/docs/CONFIG.md`
- `stacks/idc1-portainer/README.md`

Connection endpoints (on the Docker host running the Portainer stack):
- **Portainer API base:** `http://127.0.0.1:9000`
- **Portainer MCP (HTTP/SSE):** `http://127.0.0.1:3052/mcp?app=windsurf`
- **Portainer MCP health:** `http://127.0.0.1:3052/health`
- **Portainer MCP (WebSocket gateway):** `ws://127.0.0.1:18183/ws`

Read-only vs write tools:
- By default this stack runs Portainer MCP in **read-only** mode (`PORTAINER_READ_ONLY=1` in `stacks/idc1-portainer/.env`).
- If you need redeploy tools (start/stop/update stack), set `PORTAINER_READ_ONLY=0` and recreate the `mcp-bundle` container.

Verify deployed image/digest via Portainer MCP (recommended)
1. In your MCP client (Windsurf/Jarvis), run `tools/list` and confirm the Portainer tools are present (prefix varies by client):
   - Look for: `portainer_*`
2. Use a Portainer MCP “list containers” / “inspect container” tool to locate the running `jarvis-backend` container in the `idc1-assistance` stack.
3. Capture these fields from the container inspect output:
   - Image reference / digest (e.g. `RepoDigests`)
   - Image ID
   - Container `Created` / `StartedAt`
4. Compare against expected deployment:
   - CI `head_sha` from `GET /github/actions/latest`
   - The expected GHCR image tag for that SHA:
     - `ghcr.io/tonezzz/chaba/jarvis-backend:sha-<head_sha>`
     - (and/or use `RepoDigests` from image inspect)

Optional: redeploy stack via Portainer MCP
- Stop/Start:
  - `portainer_1mcp_stopLocalStack`
  - `portainer_1mcp_startLocalStack`
- Update stack file + redeploy:
  - `portainer_1mcp_getLocalStackFile`
  - `portainer_1mcp_updateLocalStack`

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

Common failure mode:
- If GitHub endpoints fail with `missing_github_personal_token_ro`, the backend is missing `GITHUB_PERSONAL_TOKEN_RO`.

### Canonical deploy flow (Docker host)
- Run: `./scripts/deploy-idc1-assistance.sh`
- Source of truth config: `stacks/idc1-assistance/CONFIG.md`

### Persist the snapshot (optional but preferred)
- If you want “what was deployed” recorded for later comparison, persist it as a **single upserted status**:
  - **Preferred:** memory key `runtime.deploy.snapshot.latest` via `POST /jarvis/memory/set`
  - **Fallback:** sys_kv key `runtime.deploy.snapshot.latest` via `POST /jarvis/sys_kv/set`

Memo text template (value to store):
- `deploy_snapshot ts=<iso> env=idc1-assistance git_sha=<sha> image_tag=<tag> instance_id=<id> uptime_s=<n> ci_status=<status> ci_conclusion=<conclusion> ci_url=<url> ci_head_sha=<sha>`

Example (preferred upsert):
1. `POST /jarvis/memory/set`
   - Body:
     - `key=runtime.deploy.snapshot.latest`
     - `value=<deploy_snapshot ...>`
     - `scope=global`
     - `priority=0`
     - `enabled=true`

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