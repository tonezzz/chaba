# Dispatch outcome — kanban-autoretry-off-by-one

## Task

`scripts/board/kanban-dispatch.py merge_pending_one`: drop the `+1`
double-count on `action.attempts` — `mark_start` already increments it at
each claim, so the requeue predicate should be
`int(a.get('attempts') or 0) < max_att`, matching the card template's
'max_attempts: total dispatches incl. auto-retries (default 2)' and
merge-sweep `fail_attempt` (the corrected sibling).

## What changed

- `scripts/board/kanban-dispatch.py` — `merge_pending_one` now reads
  `att = int(a.get("attempts") or 0)` (no `+1`) and no longer writes
  `a["attempts"]` back; the merge step never consumes a dispatch slot.
  Comment updated to state the claim-time counting invariant. Comms /
  ops_event strings still print `attempt {att+1}/{max}` — the *upcoming*
  attempt number, same convention as `fail_attempt`.
- `scripts/board/merge-sweep.py` — comment-only: the `fail_attempt` note
  now records that `merge_pending_one` uses the same predicate (the stale
  "double-counts" warning moved to past tense).
- `tests/board/test_dispatch_close_out.py` — `MergeRetryTest` fixture now
  reflects the real post-claim state (`attempts: 1`); it is a true
  regression test (under the old arithmetic `2 < 2` would refuse the
  requeue). Added: budget-exhausted (`attempts=2`, default cap → no
  requeue), `max_attempts: 3` card override (`attempts=2` → requeues,
  "attempt 3/3"), and `KANBAN_AUTORETRY=0`. Helper `_merge_card` dedups
  the mock/plumbing.

## Result

- Before: at default `max_attempts=2`, one claim (`attempts=1`) + one
  failure gave `att=2`, `2<2` false → auto-retry never fired.
- After: `attempts=1 < 2` → requeued with `last_failure`; the retried
  claim bumps to `attempts=2`; a second failure hits `2<2` false → stays
  in review `verified=False` for a human. Total dispatches = max_attempts.

## How to verify

```
python3 -m pytest tests/board/test_dispatch_close_out.py -x -q   # 20 passed
python3 -m pytest tests/board -x -q                              # 93 passed
```

End-to-end once merged: fail a dispatch merge (e.g. red test gate) on a
card with default attempts — comms should show
`auto-retry queued (attempt 2/2)` instead of silence.

## Follow-ups filed

- `kanban-parked-retry-dead-end` — nothing resets `action.attempts`, so a
  card parked by `attempts >= retries_per_card` can never be revived:
  `process` re-parks it, `retry` bumps attempts again (same double-count
  shape vs `mark_start`).

## Trail

- Job note: `docs/ssot/jobs/kanban/2026-10-10-autoretry-off-by-one.yml`

lessons:
- action.attempts is claim-side accounting (mark_start) — merge/close-out paths must read it, never increment or rewrite it.
- max_attempts means total dispatches including the first run (default 2 = 1 run + 1 retry), not "retries".
- Regression fixtures need the realistic post-claim state (attempts: 1); a fixture with attempts unset masked the off-by-one.
- File new kanban cards via POST /card on board-api — never edit card YAML directly (flock races).
