# m1-stream-test-hook — outcome

## What changed

**mddb-fork** (`~/CascadeProjects/mddb-fork` on idc02): commit `c66b563` on
branch `dispatch/20261025-055220-m1-add-a-stream-state-test-hoo`, based on
`ed1ff11` (the m1-behavioral pinned parent) — **unpushed**, per dispatch
rails.

- `ReplicationClient` gains `connected atomic.Bool`, wired in `replicate()`
  (set when the binlog stream establishes) and `disconnect()` (cleared) —
  same semantics the real fix `c0850f0` uses.
- New test-only hook:

  ```go
  SetStreamStateForTest(connected bool, lagMs int64, lastAppliedAt time.Time, appliedLSN uint64)
  ```

  It writes the same atomics the loop maintains, so a held-out test can model
  "connected, caught up, leader quiet for 2h" without a live stream.
  `IsHealthy` and the handler are untouched at this base — the health fix
  remains the agent's job.

**Live task** (`dell:~/evals/tasks/m1-behavioral/`):
- `tests/behavioral_test.go` now includes
  `TestFollowerHealthIdleCaughtUpStaysHealthy` — drives the hook, asserts
  `rc.IsHealthy()` and the handler's `healthy:true`. It resolves the hook via
  interface assertion and `t.Skip`s when the base lacks it, so it was deployed
  live immediately without changing current scores.
- `task.yaml` annotated (comment only) with the activation step.

## Control validation (dell, `score.py` + extended test)

| workspace | score | meaning |
|---|---|---|
| plain `ed1ff11` (current ref) | 0.667 (2/3) | idle test self-skips; live task unchanged |
| `ed1ff11`+hook (new base) | 0.5 (2/4) | idle test runs, catches time-based health |
| `c0850f0`+hook (fix) | 1.0 (4/4) | hook-driven connected+lag passes end-to-end |

Validation kit left on dell: `/tmp/m1hook-{plain,parent,fix}` worktrees,
`/tmp/m1hook-{parent,fix}.patch`, `/tmp/m1hook-task/` taskdir.

## Activation (needs a push — not done per rails)

```sh
cd ~/CascadeProjects/mddb-fork
git push github-mddb dispatch/20261025-055220-m1-add-a-stream-state-test-hoo
# then on dell: tasks/m1-behavioral/task.yaml repo.ref -> c66b563
```

Until then the gate stays 3-test; after the bump it is 4-test and also
rejects fixes that keep time-since-last-entry health — the residual gap the
card targeted.

## SSOT

`docs/ssot/jobs/bench/2026-10-25-m1-stream-test-hook.yml`
