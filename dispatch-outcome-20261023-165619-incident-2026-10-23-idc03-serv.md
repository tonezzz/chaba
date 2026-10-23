# Dispatch outcome — kanban-commit rebase deadlocks on card divergence

Card: kanban-commit-reconcile-rebase-deadlocks-4d95a9
Incident: 2026-10-23 — idc03 served checkout diverged 275 commits;
`kanban-commit.service` failed every 15-min tick all day on
"pull --rebase needs manual resolution" while ~6h of board writes piled
up unpushed.

## What changed (commit 0bef5fa9 on the session branch — not pushed)

1. **Union merge driver** — new `scripts/board/merge-card-yaml.py`, a git
   merge driver (`card-union`) bound to `docs/ssot/kanban/cards/*.yml`
   via `.gitattributes`. It reuses `reconcile-local-conflicts.merge_cards`:
   comms unioned+deduped on (at|ts,from,text), requests merged by id,
   action/ask/pipeline per-key union, board scalars won by newer
   `updated`, generic keys won by %A/ours. Card content conflicts now
   merge INLINE during rebase/merge instead of sidecar-deadlocking.
   `git-safe-pull.sh` self-arms `merge.card-union.driver` +
   `info/attributes` every run (covers trees that predate
   `.gitattributes`; falls back to the running script's own copy for
   checkouts that haven't pulled it yet). `install-hooks.sh` arms it for
   manual merges.

2. **Merge fallback** — `git-safe-pull.sh`: when the rebase still can't
   complete (>25 conflicted steps, --continue failure, non-generated
   conflict), one `git merge $UPSTREAM` replaces the replay — a single
   conflict point regardless of divergence depth. Cards union via the
   driver; other generated paths resolve upstream-wins (`--theirs`
   mid-merge) preserving the local side as `.local-conflict-*`;
   non-generated conflicts abort and keep the exit-1 contract.
   `SAFE_PULL_NO_REBASE=1` = testing knob/escape hatch.

3. **Write-path contract — decided: accept.** Dispatch worktree card
   writes stay allowed (`dispatch_repos._merge_in` now passes the driver
   via `-c`, so session card writes union with live board state instead
   of being dropped by the generated-paths `--ours` rule). board-api
   remains the preferred write path; the driver is the convergence
   layer. Rationale + revisit note in
   `docs/ssot/jobs/kanban/2026-10-23-card-union-merge-driver.yml` and
   AGENTS.md write-path bullet.

4. **Failure-streak alert** — `kanban-commit.sh` counts consecutive
   nonzero exits in `$gitdir/kanban-commit-fail-streak`; at
   `KANBAN_FAILURE_ALERT_AFTER` (default 3 ≈ 45 min) it upserts
   `ops-kanban-commit-guard` (static note → bumps `updated`, no per-tick
   comms spam). A healthy tick clears it; recovery after an alerted
   streak appends "recovered after N consecutive failed ticks" to the
   alert card.

## How to verify

- `python3 scripts/board/merge-card-yaml.py --selftest` — OK
- `python3 scripts/board/reconcile-local-conflicts.py --selftest` — OK
- `bash tests/test-kanban-commit.sh` — **59/59 pass** (cases A–J; new
  H=union rebase, I=merge fallback, J=streak alert+recovery)

## Notes

- Pre-existing caveat carried into the driver: union merge never
  propagates deletions (a comm removed on one side survives from the
  other) — documented in the job yml.
- Deploy: nothing was pushed or deployed; the served checkout picks this
  up on its next sync, and `git-safe-pull.sh` self-arms the driver on
  the very pull that delivers it (bootstrap fallback).
