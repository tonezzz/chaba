# dispatch-outcome — dispatch-merge-sweep re-verification (2026-11-18)

## What happened

This session was a user-triggered re-dispatch of card `dispatch-merge-sweep`,
which is already `column: done` + `action.status: done` + `verified: true`
(shipped 2026-10-08, OPS-0200). The card file on origin/master is identical to
this worktree's copy — nothing was re-opened. No code changes were needed or
made.

## Verification against the card spec

`scripts/board/merge-sweep.py` (1703 lines) implements every spec bullet:

- Enumerates doing/review cards with `action.type=dispatch` and resolves the
  session (task_id → claim.session → `started devin-task-<id>` comms →
  runner-agent state.json) — `sweep_card()`, `load_dispatch_cards` filter.
- Locates the runner worktree via the meta.json pattern
  (`~/.local/share/devin-dispatch/tasks/<tid>/meta.json`) — `REMOTE_SESSION_PROBE`
  with `dispatch-wt-<id>` / branch fallbacks.
- Verifies the runner worktree HEAD is clean (dirty = comms flag, never
  auto-committed) and ahead of base.
- Fetches via `git -c core.sshCommand=ssh fetch <runner>:<worktree> HEAD` —
  `fetch_session()` (the `-c` override defeats the repo's GitHub-only pinned
  key). Fallbacks: session branch on origin, then relayed git bundle via
  `$DISPATCH_DIR/patch-inbox/`.
- Merge policy = stop-and-report: `merge_strict()` + `dr.merge_state()` in a
  detached worktree of the served checkout; ANY conflicted path aborts and
  posts a card request naming the files (`card_request()`/`conflict_rid()`);
  clean merge pushes `HEAD:<base>` + card comms. `dispatch_repos` is reused
  (`import dispatch_repos as dr`) as the spec requires.
- Cadence: spec asked for `merge-sweep.timer` on dell; architecture evolved —
  merge-sweep is sub-check #1 of `board-janitor.py`, driven by
  `board-janitor.timer` on idc03 every 15m (`ssot.jobs.yml`, job
  `board-janitor`, OPS-1244d; writer moved dell→idc03).
- Zombie lane: `REMOTE_ZOMBIE_PROBE` + `zombie_probe()` flag `devin-task-*`
  units >6h old with >60min idle in card comms; never auto-kills.
- Acceptance was already evidenced live on 2026-10-08 (3 stranded branches
  fetched off runners, conflicts → requests, per card comms).

## Test result

`python3 -m pytest tests/board/test_merge_sweep.py` — **41/41 pass** (10.4s).

## Board state

- Posted one card comms line documenting the re-dispatch + verification.
- No requests raised, no card fields mutated.
- Open follow-ups already exist as separate cards and were not touched:
  `merge-conflict-requests-re-raise-*` (doing — answered merge-conflict
  requests re-raise every sweep), `merge-sweep-test-gate-fail-open`
  (backlog — pytest-less hosts merge with no test evidence),
  `merge-sweep-verify-durable-work-*` (done).

## How to verify

```
python3 -m pytest tests/board/test_merge_sweep.py -q
grep -n "merge-sweep" scripts/board/board-janitor.py
grep -A5 "id: board-janitor" docs/ssot/infrastructure/ssot.jobs.yml
```
