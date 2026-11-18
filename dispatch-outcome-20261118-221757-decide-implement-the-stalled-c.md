# Dispatch outcome — stalled-claim lifecycle (dispatch-failed-cards-park-in-doing)

## What changed

**The rule implemented:** `doing` means a live claim exists. Every path
that ends a claim now releases the column; every path that starts one
now stamps it.

- `scripts/board/board-api.py`
  - `do_claim`: refuses at `action.attempts >= max_attempts`
    (KANBAN_MAX_ATTEMPTS=2 default, per-card `max_attempts` override),
    bumps `attempts`, stamps `claim.since`, moves any non-terminal
    column to `doing`.
  - `do_finish` failure: records `action.last_failure`, clears
    runner/task_id/claim.session, then **auto-requeue**
    (`queued`+`backlog`) under the cap — or parks `failed` in `backlog`
    at the cap. KANBAN_AUTORETRY=0 skips the requeue. Success path
    unchanged (`done`→`review`).
  - `do_action` verbs: `queue` now releases `doing` cards (was
    done/review only) and clears `claim.session`; `retry` clears
    session/task_id, **resets attempts to 0** (the human re-arm), and
    moves doing/review/done → backlog.
  - `queue_view` (GET /queue): `claimed[]` counts `starting` alongside
    `claimed`/`running` — a local dispatch mid-launch is a live claim.
- `scripts/board/kanban-dispatch.py`
  - `mark_start`: bumps `attempts`, stamps `claim.since`, sets
    `column=doing` (local claims were invisible before).
  - new `_fail_or_requeue(card, why)` — the one dead-claim rule — wired
    into `finish_one` (failed unit + proven-bad exit branches),
    `start_pending` (launch failure), `merge_pending_one`
    (auto-requeue → backlog), `requeue_dead` (dead-runner → backlog),
    and the retry-cap `held` park (→ backlog, comms points at
    `/action do=retry`).
- `scripts/board/merge-sweep.py` — **stalled-claim reaper lane**
  (`reap_stalled_claims`), runs inside board-janitor's 15-min tick on
  the served checkout after the zombie sweep:
  - `running`/`claimed` + live unit or fresh runner heartbeat →
    untouched; + no evidence + claim older than `STALLED_CLAIM_HOURS`
    (6h) → **flagged** (comms + `action.sweep.stalled_claim` +
    `awaiting_action`), never auto-requeued — an unprobeable runner's
    session may still be alive.
  - `done`→`review`, `failed`/`held`/`queued`/settled-`starting`→
    `backlog` — provably-dead statuses take the honest column under one
    locked write that re-verifies state (no stomping a fresher claim).
  - no claim evidence past `ORPHAN_DOING_HOURS` (24h) → flag-then-move:
    flag first sighting, move to backlog on a later still-untouched
    pass (could be real offline work).
  - `fail_attempt` (verified gate) now also moves doing/review →
    backlog on requeue/fail.
- `tests/board/test_stalled_claim_lifecycle.py` — 23 new cases;
  `tests/board/test_dispatch_close_out.py` re-pinned to the new
  lifecycle.
- `docs/ssot/jobs/kanban/2026-11-18-stalled-claim-lifecycle.yml` —
  durable job/runbook record (semantics, knobs, deploy path).

## Result / verification

- `pytest tests/board/` — **664 passed, 8 subtests** (incl. all 23 new
  lifecycle cases).
- `board-api --selftest` — ok.
- **Live E2E** — real `board-api` HTTP server against a temp card store
  (BOARD_API_COMMIT=0), driving the actual `/action` write path:
  **27/27 checks** — failed finish → queued+backlog and visible in
  `/queue queued` (claimable); re-claim → doing + attempts+1 +
  claim.since; cap → failed+backlog + claim refused; retry →
  queued+attempts=0; `queue` verb → backlog; and **board doing-count ==
  /queue claimed** at every step.
- `merge-sweep --dry-run` from a readonly checkout correctly refuses via
  the chaba-role guard — the reaper writes only on the served writer.

## How to verify after deploy

The changes ride the normal merge → chaba-repo-sync → board-api restart
path (not deployed from this worktree). On idc03 after merge:

- `curl -s http://127.0.0.1:8787/queue` — `claimed[]` should equal the
  cards in `doing`; `queued[]` is the claimable backlog.
- Next board-janitor tick (~15 min): stale doing cards gain
  `stalled-claim reaper:` comms; dead statuses move to
  backlog/review.
- A deferred/failed dispatch card returns to `backlog` and is
  re-claimable.

## Notes

- Committed on the dispatch branch only — no push, no deploy, no
  default-branch commit.
- No questions were raised; `$TASK_DIR/answers.jsonl` does not exist.
- Thresholds are env knobs (see job doc): KANBAN_MAX_ATTEMPTS=2,
  STALLED_CLAIM_HOURS=6, ORPHAN_DOING_HOURS=24, STARTING_SETTLE_MIN=30.
