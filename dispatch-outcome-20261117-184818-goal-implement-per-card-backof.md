# Dispatch outcome — dispatch-retry-storm-worktree-flood

## Goal
Implement per-card backoff and a live retry cap in the dispatch loop on
tony-omen to stop worktree floods like the ~130 accumulated Nov 8-9
(timer-log-shipper-severe, ada-proactive-digest-morning-b, etc.).

## Root cause found
board-api `do_finish` sets `action.status=failed`; producers re-arm the
card (POST /card `on_exists=queue` → "re-spawned from report page",
timer-sentinel re-opens) every ~15-30 min. runner-agent's `claim_pass`
claimed it instantly each cycle — no backoff, no dedupe — and each claim
spawned a fresh dispatch worktree. kanban-dispatch's existing
`retries_per_card` policy + `attempts` counter never applied: runner
claims go through `/action do=claim`, which doesn't count attempts.

## What changed — `scripts/board/runner-agent.py`
- New per-card retry ledger `RUNNER_STATE/retry-ledger.json`:
  `{cid: {fails, last_fail, next_ok, rearms}}`.
- `retry_record_failure` called on every claim-time failure path:
  `finish_pass` terminal drop with ok:false (fetches the card for the
  re-arm baseline), `claim_pass` start_task failure, `reconcile_pass`
  zombie-restart failure. `retry_record_success` clears the entry.
- `retry_gate(card)` consulted in `claim_pass` (before blocked_by) and
  `verdict_pass` (so `/ready` shows the hold reason, not "eligible"):
  - `now < next_ok` → "retry backoff until …" (exponential:
    `min(6h, 30m * 2^(n-1))` by default)
  - `fails >= RETRY_MAX` (default 3) → "retry cap" + comms note +
    `awaiting_action` for human triage
  - a deliberate re-arm forgives the ledger — detected by counting the
    retry/queue verbs' comms markers ('retry requested', 're-queued',
    'queued for processing'). Timestamp-free compare (board clock skew
    can't corrupt it). `action.attempts` bumps are deliberately NOT a
    forgive signal (kanban-dispatch's mark_start bumps them too — a
    sibling claim would forgive endlessly, ping-ponging the flood
    between hosts). Producer 're-spawned from report page' likewise
    never forgives — it IS the flood driver.
- Env: `RUNNER_RETRY_MAX` (3; 0 disables), `RUNNER_RETRY_BACKOFF_S`
  (1800), `RUNNER_RETRY_BACKOFF_MAX_S` (21600), `RUNNER_RETRY_TTL_S`
  (30d prune — stale fails can't shadow a card re-queued months later).
- Ledger is per-host: a hold never pins the card; fleet-wide bound is
  RETRY_MAX × live runners.
- Deploy path: none needed — `_self_update` installs the repo copy on
  the next runner-agent tick after merge + chaba-repo-sync.

## Tests
- New `tests/board/test_runner_agent_retry.py` — 16 cases: exponential
  backoff math, cap + awaiting note, producer re-spawn never forgiving,
  retry/queue comms forgiving, attempts-bump NOT forgiving,
  missing-baseline entries, disabled gate, claim_pass never POSTing a
  claim while held.
- Isolated `RETRY_FILE` into tmpdirs in `test_runner_agent_reconcile.py`,
  `test_runner_agent_lane.py`, `test_claim_order.py` (previously the
  reconcile test wrote a stray entry to the real
  `~/.local/share/runner-agent/retry-ledger.json` — cleaned).

## Verification
- `python3 -m pytest tests/board/` — **609 passed** (full suite).
- Dry-run simulation of the actual flood (producer re-arm every 15 min
  for 36h, every start fails): **3 claims total** at t=15/45/105 min —
  then capped and held. Previously ~144. Comms: one bounded note per
  failure + cap note with `awaiting_action`.
- Done-condition met: the dispatch loop enforces backoff and retry
  limits on failed cards; failing cards are not re-spawned every
  15-30 minutes.

## Trail
- `docs/ssot/jobs/kanban/2026-11-17-runner-agent-retry-backoff-cap.yml`
- Committed on `dispatch/20261117-184818-goal-implement-per-card-backof`
  (e9b61028ab) — not pushed, no master commits.

## Notes / follow-ups
- kanban-parked-retry-dead-end (attempts never resets on the
  kanban-dispatch side) is a separate carded issue, untouched.
- A held card re-arms via the board ↺ Retry button or do=queue. A
  hand-edited YAML re-arm is invisible to the ledger — ops escape:
  delete `~/.local/share/runner-agent/retry-ledger.json` on the host.
