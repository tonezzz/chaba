# Orchestration conflict management — proposal

Date: 2026-09-27 · scope: Devin dispatches, Ada tool calls, job-run tasks
acting on shared resources (repos, dashboards, CMS pages, devices, hosts).

## Where conflicts bite today

| Conflict | Real example we hit |
|---|---|
| Same repo, two sessions | `pfg2-card.ts` duplicated render crash, version races → worktree-per-session rule |
| Same dashboard view | nobito + admin edits over websocket — last writer wins silently |
| Same device/entity | Ada voice toggles a plug while a job tests it |
| Same CMS slug | Ada republishes a page a dispatch session is regenerating |
| Same host lane | 3 sessions running heavy work on one host |
| Same deploy | concurrent `deploy-card.sh` — mitigated by `flock` today |

## Design: claim → check → act → release

### 1. Job claims (declared, durable)

Every dispatched/job-run task declares its **resource claims** in
`meta.json` + the job doc: `claims: [{repo: chaba, path: docs/kb/**},
{ha_view: chaba-home/nobito}, {host: tony-omen}, {device: switch.plug_tv}]`.

Dispatch wrapper derives defaults — `--repo chaba` implies
`{repo:chaba}`; `--host omen` implies `{host:omen}`.

### 2. Gate at dispatch time (not runtime)

`devin_dispatch` and `job-run start` check the job ledger first:

- **Conflict** (another `running`/`awaiting-user` job claims the same
  resource) → refuse with `conflict: job X holds repo:chaba` and let the
  caller decide: `queue` it (status `queued`, auto-starts when X closes),
  `proceed_anyway` (needs explicit confirmed), or cancel.
- Ada voice path: devin_dispatch already gates on confirmed — extend the
  deny message to name the conflicting job so Ada can tell Tony
  "job X owns chaba right now — queue it?"

### 3. Locks for hot single-writer resources

- `deploy-card.sh` already has `flock /tmp/pfg-deploy.lock` — keep.
- Dashboard mutations: `push-dashboard.py` gets a `--claim <view>` flag —
  the job doc records the view; a second mutation of the same view while
  a job holds it queues or fails loud.
- CMS slugs: `cms_publish_page` rejects if the slug is claimed by a
  running job (per-content-hash pending already exists — add claim check).

### 4. Ada voice commands vs running jobs

Voice is single-utterance — she shouldn't block. Rule:

- Voice command on a resource claimed by a running job → Ada answers
  "that's currently being changed by job X, want me to override?" —
  overrides go through the confirmed path and mark the job's doc
  `overridden_by: voice`.

### 5. Arbiter = this control desk

The foreground session is the arbiter: before dispatching N tasks, check
the ledger for overlapping claims and serialize them. The ledger query
(`devin_jobs`) already exists — extend it to return `claims` so a session
can plan a non-conflicting wave.

### 6. Resolution rules (documented precedence)

1. Explicit user instruction > everything
2. `awaiting-user` job + user answers → that job proceeds
3. Same-resource conflicts: first-claimed wins; second queues
4. Stale claims (`running` > 6h, no heartbeat) → auto-deny new writes,
   flag for review in the report feed

## What to build

| # | Piece | Effort |
|---|---|---|
| 1 | `claims` on job docs + dispatch wrapper derives them | small |
| 2 | `devin_jobs` returns claims; Ada prompt: "check conflicts before dispatch" | small |
| 3 | Conflict gate in `devin_dispatch`/`job-run` (refuse/queue/proceed) | medium |
| 4 | `push-dashboard.py --claim` + view-level lock | small |
| 5 | stale-claim sweeper in dispatch-watch (heartbeat check) | small |

## Why this shape

Fits what exists: job docs are already the durable ledger, `flock` proves
the lock pattern, `devin_pending`/`devin_jobs` gives Ada visibility. No
new infra — claims ride on MDDB job docs, no central broker needed.
