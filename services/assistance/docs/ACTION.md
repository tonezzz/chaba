# Action (Operator Playbook)

**Chat protocol:** `services/assistance/docs/CHAT_PROTOCOL.md`

**Checklist:** `services/assistance/docs/CHECKLIST.md`

## Jump
- [Now (what to do next)](#now-what-to-do-next)
- [Recent status (success / problems / next)](#recent-status-success--problems--next)
- [Docs governance (GitHub Issues SSOT)](#docs-governance-github-issues-ssot)
- [Preflight: confirm you’re using the latest ACTION.md](#preflight-confirm-youre-using-the-latest-actionmd)
- [Post-push status (do I need to redeploy?)](#post-push-status-do-i-need-to-redeploy)
- [Runbooks](#runbooks)
- [Update OVERVIEW.md (diagram + links)](#update-overviewmd-diagram--links)
- [Important warnings](#important-warnings)
- [Decision log (keep to 3 lines max)](#decision-log-keep-to-3-lines-max)
- [Improvements (pair-working backlog)](#improvements-pair-working-backlog)

## Now (what to do next)

- **Preferred (strong-standalone):**
  - **Say:** `action pc1` or `action idc1`
    - This implicitly runs: `status` (see below) and then starts the **Now** item.
  - If you only say `action`, I must ask which machine (`pc1` vs `idc1`) before proceeding.

### Strong-standalone protocol (status + action)

Definition:
- **Strong** = hard-stop on ambiguity or unsafe state.
- **Standalone** = `action <machine>` implicitly runs `status` first.

`status` (read-only snapshot):
- `git branch --show-current`
- `git status -sb`
- If reachable, check runtime health endpoints (see **Overview (quick context)**).

`action pc1` / `action idc1` (hard gates):
1. **Machine intent must be explicit**
   - Allowed: `action pc1`, `action idc1`.
2. **Branch must be explicit (deploy safety)**
   - If you intend to trigger a deploy (CI publish + Portainer redeploy), you must be on: `idc1-assistance`.
   - If you intend to do local work only, stay on a `work/...` branch and merge via PR.
3. **Working tree must be clean**
   - If dirty: stop and choose one: commit+push, stash, or discard.
4. **Integration branch safety**
   - If on `idc1-assistance`: stop unless you explicitly intend to do deploy-triggering work.
   - If you are about to redeploy, confirm Portainer stacks reference: `refs/heads/idc1-assistance`.

Once gates pass:
- **I will run:** the current `TODO.md#Now` item (currently `TODO-NOW-015`).

## Recent status (success / problems / next)

- **Success (recently completed)**
  - `#95` Bound Sheets logs payload size + retention/trim behavior (no longer the active focus).
  - Pending/confirmation tooling + macro admin tooling is working well enough to proceed with operator workflows.
- **Failures / risks (current)**
  - Docs drift/duplication: multiple sources of truth (README vs docs vs `ACTION.md`).
  - Context loss risk across redeploys/new chats unless work is consistently captured into GitHub Issues + `TODO.md`.
  - GitHub Issues via backend HTTP is gated; keep it disabled unless explicitly enabled and tokened.
- **Recommended update (right now)**
  - Treat GitHub Issue `#96` as the SSOT for the README/docs audit.
  - Remove obvious duplication and make non-operator docs link to `ACTION.md` instead of repeating runbooks.
  - Keep `TODO.md` with exactly one active **Now** item.
- **What to do next (single move)**
  - Execute `TODO-NOW-015` / Issue `#96`:
    - Inventory top-level docs (`README.md`, `services/assistance/README.md`, `services/assistance/docs/*`).
    - Decide the SSOT location for each topic and replace duplicates with pointers.
    - Verify all runbook pointers resolve and nothing essential was deleted.

## Docs governance (GitHub Issues SSOT)

Rule:
- GitHub Issues are the SSOT for doc change intent, scope, acceptance criteria, and historical context.
- Repo docs (this file + linked runbooks) are the SSOT for the current operator procedure.

Index:
- Maintain 1 pinned **Docs Index** GitHub Issue that acts as:
  - the map of `ACTION.md` + linked runbooks
  - the running changelog (links to doc-change Issues + PRs/commits)

Doc change record:
- For any meaningful doc update:
  1. Create a new GitHub Issue using the **Doc Change Record** template.
  2. Make the edit(s) and link the Issue in the PR/commit.
  3. Close the Issue and add a 1-line changelog entry to the Docs Index.

Doc drift policy:
- Avoid duplicated endpoint/procedure lists across docs.
- Prefer pointers to:
  - `GET /openapi.json` (runtime API surface)
  - `services/assistance/docs/ACTION.md` (operator runbooks)

## Runbook: Skills Sheet SSOT routing

Background + schema: `services/assistance/docs/SYSTEM.md`.

### Update the Skills Sheet

- Edit rows in the sheet identified by sys_kv key `system.skills.sheet_name`.
- Keep `name` unique.
- Use `enabled=false` to disable without deleting.
- Use `match_type=none` for inject-only rows.
- Ensure `arg_json` is valid JSON when present.

### Apply: system reload

- Trigger a backend reload (UI: Settings → System → Reload).

### Verify

1) List loaded skills:

```
/tool system_skills_list {}
```

2) Fetch a specific skill:

```
/tool system_skill_get { "name": "<skill-name>" }
```

3) Compat endpoint (clients):

```bash
curl http://127.0.0.1:18018/config/voice_commands
```

## 2-computer workflow (anti-drift mechanism)

Goal:
- Prevent accidental divergence when you use more than one machine.
- Keep deploy-triggering changes intentional.

Branch model:
- Integration/deploy branch:
  - `idc1-assistance`
  - Update via PR merges only.
- Per-machine branches (slash style):
  - `work/idc1-assistance/pc1`
  - `work/idc1-assistance/idc1`

Branch sanity check (run before edits):
1. `git branch --show-current`
2. `git status -sb`

Preferred reset commands:
- `action pc1`
  - Expected branch: `work/idc1-assistance/pc1`
- `action idc1`
  - Expected branch: `work/idc1-assistance/idc1` (or `idc1-assistance` if you are in deploy mode)

When you use a reset command, do this before anything else:
1. Run the branch sanity check.
2. If the branch is wrong, switch branches before continuing.
3. Then execute the current `Now` item.

Rules:
- Never force-push.
- Keep work on your machine branch; share changes via PRs.
- If you are unsure which branch you should be on, stop and say: `action`.

Drift triggers (say `action` immediately):
- You are about to commit/push but can’t name the target Issue you’re working against.
- You are about to push to `idc1-assistance` (integration) without explicitly intending to deploy.
- You can’t quickly answer: “which machine owns which branch right now?”
- You have more than one plausible “next step”.

Linked runbooks (map):
- `services/assistance/docs/CHAT_PROTOCOL.md`
  - Label: `docs:runbook`
- `services/assistance/docs/CHECKLIST.md`
  - Label: `docs:runbook`
- `services/assistance/docs/SYSTEM.md`
  - Label: `docs:runbook`
- `services/assistance/docs/BUILD.md`
  - Label: `docs:runbook`
- `services/assistance/docs/CONFIG.md`
  - Label: `docs:runbook`
- `services/assistance/docs/TOOLS.md`
  - Label: `docs:runbook`
- `services/assistance/docs/OVERVIEW.md`
  - Label: `docs:runbook`

### Pending Jobs (capture from chat; don’t lose work)
Use this whenever:
- You’re about to redeploy.
- You’re switching contexts.
- The chat is getting long.
- You have more than 2 pending items in your head.

Goal:
- Keep a durable, searchable list of open items.
- Avoid losing tasks across reconnects / redeploys / new chats.

Process (copy/paste friendly):
1. **Capture**
   - In the chat, ask for a single consolidated list of “pending jobs / open loops”.
   - Ensure each item is:
     - outcome-oriented
     - has a clear “done” condition
     - has the next concrete action (command or UI click)
2. **Persist**
   - Put the list into:
     - `services/assistance/docs/TODO.md` (project backlog), and/or
     - your IDE todo list (fast per-session tracking)
3. **Merge / dedupe (WIP limit = 1)**
   - If an item overlaps an existing TODO, merge instead of duplicating.
   - Keep only one `in_progress` item at a time.
4. **Sync ACTION.md**
   - Update:
     - **Current pick** (single next move)
     - status chart snapshot if you redeployed or pushed
5. **Prove it survived**
   - Re-open `TODO.md` (or the IDE todo list) and confirm the items are present.

### Convert remaining chat work into GitHub Issues (dev SSOT)
Use this whenever:
- You finished a stabilization loop and have leftover ideas/tasks in chat.
- You’re about to start “new work”.

Rule:
- GitHub Issues are the SSOT for development scope, acceptance criteria, and progress updates.
- Merge/dedupe aggressively: prefer adding to an existing Issue over creating a new one.

Gated hint:
- Optional: the Jarvis backend may expose GitHub Issues create/search/comment over HTTP, but it should remain disabled unless explicitly enabled (gated) and tokened.

Process (copy/paste friendly):
1. **Extract candidates**
   - List 3-10 short items from chat as:
     - `Title` (1 line)
     - `Done = ...` (acceptance criteria)
     - `Next action = ...`
2. **Merge check**
   - Search for overlap:
     - `gh issue list --repo tonezzz/chaba --search "<keyword>" --limit 20`
   - If overlap exists: add a comment to the existing Issue and stop.
3. **Create Issue(s)**
   - One Issue per outcome (avoid “mega issues”).
   - Include:
     - context
     - acceptance criteria
     - verification steps
4. **Link back**
   - Add a short pointer in `TODO.md` (optional) and/or in the chat.

### Snapshot procedure (copy/paste; update the status chart)
1. **Backend snapshot**
   - `GET /status`
   - `GET /health`
     - Paste: `build.git_sha`, `build.image_tag` (must be non-null)
2. **CI snapshot (this branch)**
   - `GET /github/actions/latest?owner=tonezzz&repo=chaba&branch=idc1-assistance`
3. **Decision**
   - If CI is green but `/health.build.*` doesn’t match `run.head_sha`, redeploy.

### 4 most valuable next actions (update this every time you run "Now")
1. **Do the current `TODO.md#Now` item (15-60 minutes)**
   - Rule: 1 active Now item only.
2. **Capture any open loops (5 minutes)**
   - Use: **Pending Jobs (capture from chat; don’t lose work)** above.
3. **Snapshot (5-10 minutes)**
   - Run: **Deploy/Build status awareness (save current state)** and record the key fields.
4. **Only if you touched deployment/CI (10-15 minutes)**
   - Run: **SNA for GitHub Actions watcher (deployed)**.

### Always-updated status chart (minimal; paste these fields)
- `Snapshot ts`
- `Deployed base URL`
- `instance_id`, `uptime_s`
- `health_ok` + `/health.build.git_sha`
- `CI run`: `status`, `conclusion`, `head_sha`, `updated_at`, `url`
- `jarvis-backend`: `image_tag`, `image_digest`, `image_created_at`

Need redeploy? rule (binary):
- **Yes** if CI is `completed/success` AND either:
  - `jarvis-backend image created` is older than `CI updated_at`, OR
  - (once SHA tags are deployed) running image tag is not `...:sha-<full CI head_sha>` (preferred) or `...:sha-<short CI head_sha>`
- Otherwise: **No/Unknown** (then run **Prove redeploy updated**).

Need rebuild? rule (binary, selective CI):
- **Yes** if the latest CI run is `completed/success` but the backend job did **not** publish a new backend image.
- In the publish workflow, this is usually visible as **`Build and push (CLI) = skipped`** for the backend matrix job.
- If you only redeploy without a new image being published, the container will restart on the same old digest.

### Current cautions (read before doing anything)
- If `build.git_sha` / `build.image_tag` are `null`, the running backend likely hasn’t pulled the latest image (or it was built without build args); redeploy/pull and re-check `/health`.
- GitHub Actions publishes images selectively (only images whose inputs changed).
- Empty commits typically do not rebuild images anymore; to force a rebuild, change/touch a file inside the relevant service directory.
- WIP limit = 1: if you start a new thing, merge it into the existing checklist/backlog section (see **Intake/merge policy** below).

### Current pick
- `TODO-NOW-015`: GitHub Issue SSOT — `#96` README/docs audit (align pointers + remove duplication)

GitHub Issue SSOT rule:
- For development work, the GitHub Issue is the SSOT for scope, acceptance criteria, and progress updates.
- `ACTION.md` stays focused on operator runbooks, snapshot/verification procedures, and “what to run next”.

Update rule:
- After you run any ACTION.md procedure, always come back here and set **Current pick** to the *single* next move.

## Runbooks

### Update OVERVIEW.md (diagram + links)
#### Goal
- Keep `services/assistance/docs/OVERVIEW.md` as the SSOT for the current project overview + latest architecture diagram.

#### When to run
- After any meaningful architecture, routing, deploy, or stack layout change.
- Before handing off work to another chat.

#### Checklist
1. Update `services/assistance/docs/OVERVIEW.md`:
   - Update **Current architecture (latest)** Mermaid diagram.
   - Update **Links** (new runbooks, stacks, dashboards).
   - Update **Conventions** if a new rule was discovered.
   - Update **Last updated** fields.
2. If the change was driven by a discussion/decision:
   - Add/attach the relevant GitHub Issue link under **Last updated**.
3. Sanity check:
   - Confirm Mermaid renders on GitHub (preview in PR or open the file on GitHub).

#### Done
- `services/assistance/docs/OVERVIEW.md` reflects the current system and includes an up-to-date diagram.

### SNA for GitHub Actions watcher (deployed)
#### Inputs you must decide (fill before running)
- **Base URL:** `https://assistance.idc1.surf-thailand.com/jarvis/api`
- **Repo:** `tonezzz/chaba`
- **Branch:** `idc1-assistance`
- **Event:** optional (e.g. `push`, `pull_request`)
- **Poll seconds:** default is fine unless debugging
- **Stop on completed:** `true`
- **Max runtime seconds:** e.g. `900` (15m)

#### Goal
- Start the watcher on the deployed backend for the target repo/branch, then verify it transitions to stopped when CI completes (or times out), and confirm `latest` + UI log updated.

### Deploy/Build status awareness (save current state)
#### Goal
- Be able to answer:
  - “What version is deployed right now?”
  - “Is the backend healthy?”
  - “What’s the current CI run status for this branch?”
  - “Did the deploy actually update?”

Notes (from `stacks/idc1-assistance/CONFIG.md`):
- Public WS URL is `wss://assistance.idc1.surf-thailand.com/jarvis/ws/live`.
- Backend serves WS internally at `/ws/live` (edge proxy must strip `/jarvis`).
- Hitting a WS URL as plain HTTP GET may return `404`; use a WS client.

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
- **Host port binds (split stacks):**
  - `127.0.0.1:18018` -> `jarvis-backend:8018`
  - `127.0.0.1:18080` -> Jarvis frontend container
  - `127.0.0.1:18030` -> `deep-research-worker:8030`
  - `127.0.0.1:3051` -> `mcp-bundle:3050`
  - `127.0.0.1:3053` -> `mcp-image-pipeline:3050`
  - `127.0.0.1:18182` -> `mcp-ws-gateway:8182`
  - `127.0.0.1:18183` -> `mcp-ws-gateway-portainer:8182`
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

Smoke check:
- `bash scripts/idc1-assistance-smoke.sh`

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

(removed)

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

### Memo (Thai commands + schema notes)
- Canonical memo header is enforced on-write (see `MEMO.md`).
- Thai commands:
  - `สรุปเมโม <id>`
    - Uses the memo already in session context if it matches `<id>`, otherwise loads from the memo sheet.
    - Output is adaptive (short memos: concise bullets; long/complex: sectioned markdown).
  - `แก้ไขเมโม` / `ปรับปรุงเมโม`
    - Hybrid flow: collects the new memo text, then requires explicit confirmation (`ยืนยัน` / `ยกเลิก`) before writing to the sheet.

Local verification (jarvis-backend):
- `python3 -m venv services/assistance/jarvis-backend/.venv`
- `services/assistance/jarvis-backend/.venv/bin/pip install -r services/assistance/jarvis-backend/requirements.txt`
- `services/assistance/jarvis-backend/.venv/bin/python -m pytest -q services/assistance/jarvis-backend`

### Logs (UI/WS)
1. **UI log**
   - `GET /jarvis/api/logs/ui/today`
2. **WS log**
   - `GET /jarvis/api/logs/ws/today`

## Verify counts: memo rows + memory items loaded
Use this when Jarvis says things like: “I have **7 memory items loaded**” or when you want to confirm memo actually appended.

### Proposal: `sheet_item_count` tool (recommended)
Goal: a single, stable way to answer “how many items are in sheet X?” without relying on UI caching or ad-hoc parsing.

- **Better name:** `sheet_row_count` (more precise) or `sheet_item_count` (OK if we define “item” clearly).
- **Where to implement (preferred):** Jarvis backend endpoint + optional Jarvis tool wrapper.
  - Endpoint: `GET /jarvis/api/debug/sheet_row_count?spreadsheet_id=<id>&sheet=<tab>&has_header=true`
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
    - `GET /jarvis/api/debug/sheet_row_count?sheet=memo&has_header=true`
  - Logs rows:
    - `GET /jarvis/api/debug/sheet_row_count?sheet=logs&has_header=true`

### Check counts (single call)
- `GET /jarvis/api/debug/counts`
- Expected fields:
  - `memory.count` (number of enabled memory items loaded)
  - `memory.cached_count` (may be 0 if not preloaded yet)
  - `memo.rows` (number of memo rows excluding header)
  - `memo.sheet` / `memo.spreadsheet_id` (where it wrote)

### If `/jarvis/api/debug/counts` is 404
- This usually means the deployed container hasn’t picked up the latest code yet.
- Fallback checks:
  1. **Memory count (backend prewarm)**
     - `GET /status`
     - Use: `startup_prewarm.memory_n` (this is the last prewarm load count; may be 0 if prewarm is disabled or didn’t load memory).

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