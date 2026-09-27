---
title: Ada → Devin Handoff Workflow (SOP)
description: Standard operating procedure for the voice-planned, headless-executed workflow — Ada drafts specs and reports into the devin-handoff memory bank, then dispatches Devin sessions on tony-dell to execute them in isolated worktrees
tags: [ada, devin, dispatch, handoff, workflow, runbook, sop]
created: 2026-09-27
updated: 2026-09-27
category: operations
status: verified
last_verified: 2026-09-27
verification_method: verified against live system — this document was itself produced by a dispatched session (task 20260927-215428) launched from spec extract-2026-09-27-fd98e6e49c-0 through exactly this pipeline
scope: Ada voice/PWA instances (mn01, idc01) dispatching to devin-dispatch hosts (tony-dell primary, tony-omen); repos chaba, ada-pi, sunsynk-card
owner: tony
related:
  [
    scripts/devin/devin-dispatch.sh,
    scripts/devin/devin-dispatch-watch.sh,
    scripts/devin/render-handoff-inbox.py,
    docs/ssot/jobs/ada/2026-09-22-ada-devin-dispatch.yml,
    docs/ssot/ssot.learning.ada-devin-dispatch.2026-09-24.yml,
    docs/ssot/apps/ssot.apps.ada-memory-banks.yml,
    docs/ssot/focus-inbox/handoff-extract-2026-09-27-fd98e6e49c-0.yml,
  ]
search_keywords: [ada devin handoff, devin_dispatch, devin-handoff bank, focus-inbox, dispatch sop, job ledger, needs-input]
---

# Ada → Devin Handoff Workflow (SOP)

**Abstract**: The standard way work flows from a conversation with Ada to an
executed code change. Ada is the planning/drafting/tracking layer; Devin is
the execution layer. The `devin-handoff` MDDB bank is the shared medium: Ada
writes specs into it, `render-handoff-inbox.py` surfaces them to repo triage,
`devin_dispatch` launches a headless `devin -p` session in a dedicated
worktree, and `devin-dispatch-watch` reports the outcome back into the same
bank as a `job/<id>` ledger doc.

## Roles — who does what

| | Ada (voice/PWA assistant) | Devin (dispatched CLI session) |
|---|---|---|
| Plans the work | ✅ discussion, Before/After analysis, trade-offs | ❌ |
| Drafts the spec/report | ✅ into `devin-handoff` bank (confirmed `ada_remember` or auto-extract) | reads it via mddb MCP |
| Executes repo work | ❌ never edits repos | ✅ worktree-isolated `devin -p` |
| Tracks progress | ✅ `devin_status` / job ledger docs | — |
| Steers mid-run | ✅ `devin_followup` (confirmed) | receives follow-up turns |
| Reports outcome | ✅ recalls `job/<id>` + `devin/<sid>` docs to Tony | writes summary as last agent message |

**Rule of thumb**: if the task is words, analysis, or a plan — Ada drafts it.
If it needs files changed, builds, tests, or shell access — Devin executes it.
Ada never does repo work herself; a dispatched session never converses, so the
spec must be self-contained.

### When Ada drafts vs. when Devin executes

- **Ada drafts** (no dispatch yet): open-ended discussions, Before/After
  analyses, investigation plans, "think about X and write it up" requests.
  Output goes to the appropriate memory bank; implementation specs go
  specifically to `devin-handoff`.
- **Ada drafts AND Devin executes**: implementation work the user wants done
  later or autonomously. Ada saves the spec, then either dispatches
  immediately (explicit user request) or leaves it in the bank/inbox for
  triage.
- **Devin executes directly**: Tony says "start a Devin session on tony-dell
  for X" — Ada restates repo + task, gets an explicit yes, calls
  `devin_dispatch` with `confirmed=true`.

## The handoff spec format

### 1. The MDDB bank doc (source of truth)

- **Collection**: `ada-ha-bank-devin-handoff` — the `devin-handoff` bank
  registered in `docs/ssot/apps/ssot.apps.ada-memory-banks.yml`
  (`writable: true`, `write_policy: confirmed`,
  `allowed_tools: [ada_remember, ada_forget, ada_outcome]`).
- **Body** (`contentMd`): a short, self-contained markdown spec — what to do,
  where, constraints, and the bank doc key to reference. Rendered text is
  capped at 3000 chars; longer specs truncate with a pointer to the key.
  No secrets — a headless agent consumes this verbatim.
- **Meta fields that matter**:
  - `subject` — becomes the rendered entry title
  - `kind` — `note` | `fact` | `procedure`
  - `status` — `draft`/`active` render into the inbox; dead states
    (`retracted`, `superseded`, `archived`, `done`, `answered`) remove it
  - `repo` / `applies_to` — whitelist `{chaba, ada-pi, sunsynk-card}`,
    default `chaba`; becomes the inbox `branch`
  - `priority`, `tags` — carried through
- **Key conventions**:
  - `extract-<date>-<sessionid>-<n>` — conversation-extracted specs
    (`written_by: conversation_memory`, e.g. `extract-2026-09-27-fd98e6e49c-0`)
  - `devin-handoff/<slug>` — explicit `ada_remember` saves
  - `job/<task-id>` — **live job ledger**, written by `devin-dispatch`/watch,
    not a spec source (see Outcome reporting)
  - `answer/<job-id>` — Tony's console answers to awaiting-user jobs

### 2. The rendered focus-inbox entry (triage surface)

`scripts/devin/render-handoff-inbox.py` renders each live bank doc to
`docs/ssot/focus-inbox/handoff-<slug>.yml`. It runs at the tail of
`devin-dispatch-watch.timer` (every 5 min on tony-dell) and manually;
idempotent, and GCs rendered files when the bank doc dies — but only files
carrying its `render-handoff-inbox` marker.

```yaml
title: standard-workflow-ada-devin           # meta.subject or first H1
subtitle: 'Devin handoff spec: extract-2026-09-27-fd98e6e49c-0'
icon: robot
focus:
  label: standard-workflow-ada-devin
  text: <spec body, capped at 3000 chars>
  branch: chaba                              # from meta repo/applies_to
  priority: medium
  status: draft
  tags: [devin, handoff, ...]
  safe_to_parallel: {value: true, reason: "Spec document; execution goes
    through devin_dispatch which creates an isolated worktree."}
  subtasks:
    - {label: "Dispatch via devin_dispatch (repo chaba, prompt references
        bank doc extract-2026-09-27-fd98e6e49c-0)", status: not_started}
ownership: {owner: tony, session: '', locked: false, lock_reason: ''}
source: {bank_key: extract-2026-09-27-fd98e6e49c-0, renderer: render-handoff-inbox, date: '2026-09-27'}
```

These files are **generated** — never hand-edit them; change the bank doc and
re-render. They enter normal focus-inbox triage alongside other drafts.

## The dispatch flow

```
conversation ──ada_remember/extract──▶ ada-ha-bank-devin-handoff (spec doc)
                                           │
                        render-handoff-inbox.py (watch tail / manual)
                                           ▼
                          docs/ssot/focus-inbox/handoff-*.yml (draft)
                                           │
              triage / Tony: "start a devin session … check the ada handoff"
                                           ▼
              Ada devin_dispatch (confirmed=true, dedup 600s/0.6)
                                           │ ssh 192.168.2.67 (LAN IP!)
                                           ▼
              devin-dispatch start <repo> "<task>" on tony-dell
                ├─ worktree ~/CascadeProjects/dispatch-wt-<id>  (dispatch/<id>)
                ├─ task dir ~/.local/share/devin-dispatch/tasks/<id>/
                ├─ systemd-run --user --collect devin-task-<id>
                │    └─ devin -p --permission-mode $MODE --export transcript.json
                └─ writes job/<id> status=running to handoff bank
                                           ▼
              devin-dispatch-watch.timer (5 min) → outcome channels
```

1. **Spec lands in the bank** — Ada writes during the conversation (confirmed
   `ada_remember` or conversation extraction).
2. **Renderer surfaces it** — `handoff-*.yml` appears in the repo inbox on the
   next watch tick.
3. **Dispatch** — Ada `devin_dispatch(repo, task)` →
   `ssh -o BatchMode=yes 192.168.2.67 ~/.local/bin/devin-dispatch start`.
   The LAN IP is mandatory: the tailnet name hits tailscaled-ssh interactive
   re-auth and hangs (see learnings doc). In-process + remote dedup
   (600 s window, containment ≥0.6) prevents double-dispatch on model retries.
4. **Isolation** — `devin-dispatch` cuts a worktree from the host's local HEAD,
   writes `prompt.txt` with the unattended rails (worktree-only, no push, no
   deploy, `needs-input.txt` for blockers, leave a trail in `docs/ssot/jobs/`
   or `reports/`), and launches a `--collect` user unit. The wrapper records
   the real exit code to `exit_code` (the unit Result is lost to `--collect`).
5. **Steering** — `devin_followup(task_id, message)` resumes the session with
   `devin -c` as unit `devin-task-<id>-fuN`; it also clears a pending
   `needs-input.txt`. `devin_status` lists tasks/unit states.
   `devin-dispatch resume <sid>` continues a stale desktop session headlessly
   in its recorded cwd (no worktree — wrap-up/research only).
6. **Permission mode** — `DISPATCH_PERMISSION_MODE` (default `smart`). Use
   `dangerous` for real build tasks: `smart` auto-rejects tools like
   curl/pytest/systemctl and an unattended session quits on rejection. The
   worktree + prompt rails are the actual guardrails.

## Outcome reporting back to the handoff bank

`devin-dispatch-watch.timer` (every 5 min, `scripts/devin/devin-dispatch-watch.sh`)
detects finished tasks — including `--collect` GC'd units (no unit +
transcript = done; prefers `exit_code`, then journal, then transcript
inference) — reads the **last agent message** from `transcript.json`
(`devin -p` never writes `history_*.md` summaries), then fires each channel
independently:

| Channel | Target | Content |
|---|---|---|
| chaba-admin event | Events feed (local `chaba-event-log.py`, or ssh `tony-dell-lan` from other hosts) | `devin task <id>: done|FAILED|needs input` + outcome text |
| iPhone notify | `notify.mobile_app_tony_ip` via tony-ha loopback REST | title + truncated outcome/question |
| Outcome doc | `devin/<session_id>` in `ada-ha-bank-devin-tony` | `Dispatched task <id> (unit, result). <last agent message>` |
| **Job ledger** | `job/<task-id>` in **`ada-ha-bank-devin-handoff`** | `Job <id> on <host>: running|done|failed|awaiting-user.` + needs-input question + summary |

The `job/<id>` ledger is the piece that closes the loop back to the handoff
bank — the dispatch scripts describe it as "the shared job ledger Ada's
`devin_pending` and the Report tab's dispatch layer read", so "what happened
to the job I handed Devin" is answerable from the bank. A dispatched session
may also append a `RUN RESULT` section to its own spec doc (precedent:
`devin-handoff/scenario-dispatch-audit`).

**Blocked sessions**: when a session writes `$TASK_DIR/needs-input.txt`, the
watch labels it `needs input`, sets the job doc to `awaiting-user` with the
question in `meta.question` (surfaced to Ada via the job ledger), and fires a
requires-response event + notify.
The operator's answer goes back via `devin-dispatch followup`, which clears
the marker — `meta.notified_fu` versioning makes each follow-up completion
re-report on its own.

**Idempotency**: `meta.json` stamps `result`, `finished_at`, `notified_fu`,
and per-channel `event_at`/`notify_at`/`mddb_at`/`jobdoc_at` — only set on
success, so a failed channel retries next run instead of going silent.

**Spec closeout**: after the produced work is reviewed/merged, mark the spec
doc `status: done` (or `ada_outcome`/`ada_forget`). The next renderer run
GCs the `handoff-*.yml` inbox file — keeping the inbox to live items only.

## Gotchas (learned the hard way)

- **ssh must use the LAN IP** (`192.168.2.67`), never the tailnet name —
  tailscaled-ssh demands periodic browser re-auth and stalls services.
- **`devin -p` writes no session summaries** — outcome comes from
  `transcript.json`'s last agent message, not the devin bank sync.
- **`systemd-run --collect` destroys the unit Result** — the `exit_code` file
  the wrapper writes is authoritative; inference is a last resort.
- **Worktrees are cut from local HEAD** — files committed on another host
  don't exist until the dispatch host pulls; copy spec inputs explicitly.
- **Repo copies of the dispatch scripts can lag the deployed ones** — the
  live `~/.local/bin/devin-dispatch{,-watch}` gained the `job/` ledger,
  `needs-input.txt` handling, `resume`, and the ssh event fallback before the
  repo scripts caught up (observed 2026-09-27). Check the deployed copy when
  behavior doesn't match the repo.
- **Every argument is shell-quoted for ssh** — Ada's tool re-joins the command
  remotely; unquoted `( ) ; '` in task text used to break dispatch.

## Verifying the pipeline end-to-end

1. `devin-dispatch status` — task registry, unit state/result per task.
2. `devin-dispatch tail <id>` — last lines of the exported transcript.
3. MDDB: `job/<task-id>` in `ada-ha-bank-devin-handoff` flips
   `running → done|failed|awaiting-user`; `devin/<session_id>` appears in
   `ada-ha-bank-devin-tony`.
4. `python3 scripts/devin/render-handoff-inbox.py --dry-run` — what the inbox
   would look like without writing.
5. chaba-admin Events feed — `devin-dispatch` category entries.
