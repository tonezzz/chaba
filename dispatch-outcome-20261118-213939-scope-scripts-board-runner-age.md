# dispatch-runner-resilience — outcome

## What changed

**a) Salvage-before-reap** (`scripts/board/dispatch-wt-sweep.py`): the timed
reaper was the one GC path that could silently lose work — it force-removes
worktrees and `-D` deletes branches whose commits exist only locally (e.g.
the checkpoint commit a push-incapable host left behind). Before reaping it
now fetches origin and checks `git branch -r --contains <head>`; commits not
on origin are pushed to `refs/heads/wip/dispatch/<task-id>` first and the
pushed ref is logged to the card's comms (card id from task meta.json,
best-effort `/comment`). If origin is unreachable, the push fails, or HEAD
is unreadable, the worktree is KEPT. Dry-run reports "would salvage-push".
The close-path GCs (`gc_worktree`, `gc_session`, `REMOTE_GC_PROBE`,
`devin-dispatch-prune.sh`) already require the head to be an ancestor of a
pushed ref — verified, no change needed.

**b) Push-capability gating at claim time** (verified + test coverage):
both claim paths already enforce it — `runner-agent._claimable` calls
`push_capable(action.repo)` (push:<repo> label fast-path, live
`git push --dry-run` probe otherwise), and `kanban-dispatch`'s claim loop
skips `push_capable`-failing cards with a card-comms defer note.
jules/nlm_batch/kk_mac_local try-first lanes are deliberately exempt (no
local branch push); claude/opencode executors are NOT exempt. New
`KanbanDispatchGuardTest` proves a push-incapable host leaves an ada-voice
card queued, a push-capable host claims it, and the `push:ada-voice` label
fast-path claims without probing.

**c) Provider rate-limit cooldown**: canonical `RATE_LIMIT_PAT` +
`rate_limit_hit()` added to `dispatch_repos.py`; runner-agent carries a
lockstep vendored copy (single-file deploys). On `finish_pass`, a unit that
failed with a throttle signature in its collect() result or journal tail
(429/529, rate_limit_error, too many requests, RESOURCE_EXHAUSTED, quota
exceeded/exceeded-*-quota, insufficient quota, overloaded_error, throttl*)
writes `$RUNNER_STATE/ratelimit.json` holding all new claims for
`RUNNER_RATELIMIT_COOLDOWN_S` (default 1800s, re-arms per hit). The reason
rides `_capacity_reason` → claim skip + `<host> defers:` notes + /ready
verdicts, plus a finish-comms line on the failing card. `kanban-dispatch`
scans the same signature in the lock-free phase-A0 survey
(`ratelimit_scan_task`) and gates `can_claim` on its own cooldown file —
journalctl stays outside the card flock per the 2026-11-17 convoy rule.

**d) Tests** (`tests/board/test_dispatch_runner_resilience.py`, 15 cases):
salvage push on reap, keep-on-push-failure, no-salvage-when-pushed,
dry-run reporting; signature scan + vendored-parity check; cooldown arming
via finish_pass and capacity gating; kanban-dispatch push gate
(incapable/capable/label fast-path) and cooldown defers claims.

**Job record**: `docs/ssot/jobs/board/2026-11-18-dispatch-runner-resilience.yml`.

No card-schema or board-api write-path changes.

## Result

`python3 -m pytest tests/board/` → **641 passed** (includes the 15 new).
All done-when criteria demonstrated in tests: simulated GC with unpushed
commits leaves a recoverable `wip/dispatch/<tid>` ref on origin; a
push-incapable host cannot claim an ada-voice card on either claimer; a
rate-limited runner defers claims for the cooldown window.

## How to verify

```
python3 -m pytest tests/board/test_dispatch_runner_resilience.py -v
# manual reap check:
python3 scripts/board/dispatch-wt-sweep.py --dir ~/CascadeProjects   # dry-run
```

lessons:
- dispatch-wt-sweep was the only GC that could drop committed work — the
  other reapers already gate on "head ⊆ pushed ref"; check the
  force-remove paths, not just the polite ones.
- journalctl scans must stay in kanban-dispatch's phase-A0 survey, never
  inside the card flock (25s-hold convoy precedent).
- runner-agent needs vendored twins of shared tables (single-file deploys)
  — a parity test is the cheap way to keep them in lockstep.
