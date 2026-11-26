# dispatch outcome — opencode-retry-stale-worktree (OPS-1021 / OPS-1039)

## What I found

The fix was **already implemented, tested, and merged to origin/master** by the
previous dispatch attempt (2026-11-23 23:33 run, commit `b58f75984e`,
auto-merged as `4b79513c`). This attempt-2 session verified the merged work
rather than re-implementing it — re-doing it would have produced a no-op diff.

Confirmed on this checkout (HEAD `375ce1a93a` == origin/master tip):

- `git merge-base --is-ancestor b58f75984e origin/master` → true.
- `_stale_worktree_gate` (`scripts/board/runner-agent.py:3059`) runs before
  `git worktree add` in BOTH lane starters that share the `dispatch-wt-<tid>`
  path:
  - `_start_opencode_lane` — runner-agent.py:3162 (behind the
    `start_opencode_lane` lane_envelope admission gate at :3085)
  - `start_kk_mac_lane` — runner-agent.py:2696
- Gate semantics (exceed the card spec, which only asked for the opencode
  path):
  1. worktree absent → proceed.
  2. live `devin-task-<tid>` unit OR `-fuN` followup (systemd
     `list-units` / launchd plist scan via `_task_units_active`) → defer,
     tree untouched — even if a stale `exit_code` from a prior attempt
     exists.
  3. `_stale_worktree_reapable(taskdir)`: lane-family `meta.json`
     executor (`opencode*`, `kk_mac_local`) proves this machinery owns the
     dead run; otherwise requires durable finish evidence
     (`taskdir/exit_code` or `taskdir/verdict.json`). Foreign executor or
     unattributable residue → defer, never reap.
  4. Reap via `_remove_dispatch_worktree`: owning repo resolved from the
     tree's own `--git-common-dir` (survives `action.repo` changes between
     retries), `git worktree remove --force` + `prune`; unregistered
     residue falls back to `rmtree`; a still-registered (e.g. locked) tree
     defers with the git error.
  5. Taskdir evidence is never touched.
- `prepare_profile_dispatch` (runner-agent.py:2880) is pure validation — no
  filesystem writes — so running the gate after it is safe.
- The devin executor path (`scripts/devin/devin-dispatch.sh:224`) uses
  timestamped ids (`date +%Y%m%d-%H%M%S-<slug>`), so it never had the
  deterministic-tid collision — correctly out of scope.

## Verification

- `python3 -m pytest tests/board/test_runner_stale_worktree.py -x -q`
  → **12 passed** (real git worktrees in tmpdirs; systemctl/launchd stubbed;
  covers reap-on-exit_code, reap-on-verdict, reap-dead-lane-meta, defer on
  live base + `-fuN` units, defer on unattributed/foreign-executor residue,
  defer on locked tree, rmtree of unregistered residue, and two end-to-end
  `_start_opencode_lane` cases).
- `pytest tests/board/test_runner_stale_worktree.py
  test_runner_agent_lane.py test_executor_contract.py test_worktree_gc.py
  test_runner_agent_reconcile.py -x -q` → **167 passed, 17 subtests**
  (5m16s).
- Trail doc already landed: `docs/ssot/jobs/board/2026-11-23-runner-stale-worktree-gc.yml`.
- The prior run's own worktree `dispatch-wt-20261123-233259-...` was already
  GC'd by merge-sweep; `git worktree list` shows no ops-1021 leftover.

## Notes / residuals

- Card comms contained contradictory close-out lines ("auto-merged
  4b79513c → origin/master" AND "auto-merge not done: no session repo") —
  the merge verifiably landed; the second line was bookkeeping noise after
  the worktree was GC'd.
- `git worktree list` shows several stale `dispatch-wt-*` trees belonging
  to OTHER cards (yt-live-api, a-if-approved, the-goal-is-to-stop,
  investigate-and-resolve, 5x ops-1025 smoke). The new gate is preventive
  at lane start — it does not retro-clean. Those tids will be reaped by
  their own lane retries (if lane-family) or by `devin-dispatch-prune.sh`.
- Prior attempt's reported failure ("OpenCode admission requires a
  complete action.lane_envelope") was a routing/staging issue, already
  resolved when Tony pinned `executor=devin` on 2026-11-23 19:51 — not a
  code bug.

## How to verify

```
git merge-base --is-ancestor b58f75984e origin/master   # exit 0
python3 -m pytest tests/board/test_runner_stale_worktree.py -x -q  # 12 passed
grep -n "_stale_worktree_gate" scripts/board/runner-agent.py      # 2696, 3059, 3162
```

lessons:
- Check `git merge-base --is-ancestor <prior-commit> origin/master` before re-implementing — this card's fix was already merged; attempt 2 was verify-only.
- Card comms can contradict ("auto-merged" + "auto-merge not done: no session repo"); trust git ancestry over comms.
- `prepare_profile_dispatch`/lane-envelope staging is pure validation — safe to run the worktree gate after it.
- devin-dispatch.sh ids are timestamped (no tid collision); only runner-agent lane starters needed the gate.
