# dispatch-outcome — dispatch-merge-sweep re-verification #2 (2026-11-18)

## What happened

Second user-triggered re-dispatch of `dispatch-merge-sweep` today (first
re-verification ran 20:46–20:48 on idc02). The card was shipped 2026-10-08
(OPS-0200) and re-verified at 20:48; `scripts/board/merge-sweep.py` is
byte-identical to origin/master (last touched 2026-11-17 22:19 by the
board-api-lock-contention fix, before the first re-verification). No code
changes were needed or made.

## Verification against the card spec

`scripts/board/merge-sweep.py` (1703 lines) implements every spec bullet:

- Enumerates doing/review cards with `action.type=dispatch`; session
  resolution via task_id → claim.session → `started devin-task-<id>` comms →
  runner-agent state.json (`sweep_card`, `load_dispatch_cards`).
- Locates the runner worktree via the meta.json pattern
  (`~/.local/share/devin-dispatch/tasks/<tid>/meta.json`) with
  dispatch-wt-<id> / dispatch/<id> fallbacks (`REMOTE_SESSION_PROBE`).
- Verifies runner worktree HEAD clean (dirty → comms flag, never
  auto-committed) and ahead of base.
- Fetches via `git -c core.sshCommand=ssh fetch <runner>:<worktree> HEAD`
  (`fetch_session`) — the `-c` override defeats the GitHub-only pinned key.
  Fallbacks: session branch on origin, then relayed bundle via
  `$DISPATCH_DIR/patch-inbox/`.
- Conflict policy = stop-and-report: `merge_strict()` + `dr.merge_state()`
  in a detached worktree of the served checkout; any conflicted path aborts
  and posts a card request naming the files; clean merges push `HEAD:<base>`
  + card comms. `dispatch_repos` reused (`import dispatch_repos as dr`).
- Zombie lane: `REMOTE_ZOMBIE_PROBE` + `zombie_probe()` flag `devin-task-*`
  units >6h old with >60min idle in card comms; never auto-kills.
- Cadence: spec asked for merge-sweep.timer on dell; architecture evolved —
  merge-sweep is sub-check #1 of `board-janitor.py`, driven by
  `board-janitor.timer` on idc03 every 15m (ssot.jobs.yml job
  `board-janitor`, OPS-1244d; the writer moved dell→idc03 under OPS-0725,
  so idc03 is the single-writer-safe host the spec intent requires).

## Test result

`python3 -m pytest tests/board/test_merge_sweep.py -q` — **41/41 pass**
(14.0s).

## Board state

- Posted one card comms line documenting this second re-verification.
- No requests raised, no card fields mutated.
- Note for the operator: the card is `column: doing` / `action.status:
  running` because the re-queues re-opened it. The shipped work is verified;
  moving it back to review/done would stop it attracting further dispatch
  runs (each re-dispatch spends a full session re-confirming the same
  code). Field moves are left to the served-checkout writers.
- Open follow-ups remain separate cards, untouched:
  `merge-conflict-requests-re-raise-*` (doing),
  `merge-sweep-test-gate-fail-open` (backlog).

## How to verify

```
python3 -m pytest tests/board/test_merge_sweep.py -q
grep -n "merge-sweep" scripts/board/board-janitor.py
grep -A5 "id: board-janitor" docs/ssot/infrastructure/ssot.jobs.yml
```
