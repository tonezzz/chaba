# Dispatch outcome: stale non-served clones (dell ~/CascadeProjects/chaba)

Card: `stale-non-served-clones-dell-cascadeproj-efbd23` (BEN-0703) · runner mn01 · 2026-10-22

## Verdict

The card's headline problem was **already fixed before it was re-queued**. The
"219 commits behind" observation was from 2026-10-15; OPS-0479 (2026-10-16)
installed `chaba-repo-sync.timer` on dell at kanban-commit cadence plus an
`ExecStartPost` hook. Verified live on dell: timer active, ~15-min ticks
exiting 0, exec checkout only 20 behind with HEAD 19:42 today — inter-tick
drift, not staleness. `~/CascadeProjects/chaba` is the **job-execution
checkout on purpose** (ssot.jobs.yml `repo: tony_dell`) and must NOT be
removed — the card's option (a) archive-and-remove was wrong for it.

## What was the real gap, and what I changed

Agents couldn't tell which checkout they were in. Landed a per-checkout
**role marker** mechanism on the dispatch branch (commit 7d2adb7e):

- `.husky/pre-commit`: reads `<gitdir>/chaba-role`; `exec`/`readonly`
  checkouts **block `git commit`** with a pointer to the served checkout /
  dispatch worktrees. Escape: `CHABA_ROLE_COMMIT_OK=1`.
- `scripts/install-hooks.sh --role <role>`: stamps the marker.
- `scripts/check-single-writer.sh`: prints role per checkout; flags
  role-less master checkouts (the trap shape).
- `AGENTS.md`: memory line documenting roles.
- `docs/ssot/jobs/infrastructure/2026-10-22-dell-non-served-chaba-clones.yml`:
  full census + rationale.

**Design fix caught mid-work:** first attempt used `git config chaba.role` —
wrong, because linked worktrees share the common config. Dell's
`dispatch-wt-*` worktrees hang off the exec checkout itself, so a shared
config role would have blocked commits in every dell dispatch session.
Switched to a file in the per-worktree gitdir — per-worktree by
construction. Verified: four dell worktrees now hold distinct roles.

## Host state changed (reversible, non-service)

- dell: `chaba`→exec, `chaba-tony-dell`→served, `chaba-h3-tony-dell`→branch,
  `chaba-kanban-sync`→job, `chaba-tony-dell-experiment`→experiment
  (marker files in each gitdir; stray shared `chaba.role` config unset).
- mn01: `~/CascadeProjects/chaba`→exec. Its repo-sync.service had one
  transient 5-min timeout on the 12:00 UTC tick; the 13:00 tick completed in
  12s and the checkout converged to 0-behind.
- Inert until each checkout pulls a merge containing the hook change; then
  commits in exec checkouts hard-block.

## Found, not fixed (decision gated)

Two genuinely stale non-served chaba worktrees on dell (both worktrees of the
served clone → reap via `git worktree remove`, not rm -rf):
`chaba-kanban-sync` (209M, dead `.parked` unit, ~24 dirty files incl. card
edits) and `chaba-tony-dell-experiment` (53M, detached 2026-09-11, staged
experiment files — possibly the only copy). **Board request raised** asking
Tony to approve archive-diffs-then-remove; no answer before session end.
Also: 14 uncommitted focus-inbox files sit unswept in mn01's exec checkout
(single-writer stall — noted as follow-up in the SSOT doc).

## How to verify

- `ssh tony-dell 'systemctl --user list-timers chaba-repo-sync.timer'` —
  ticking; `git -C ~/CascadeProjects/chaba rev-list --count HEAD..origin/master`
  stays < ~30 between ticks.
- After merge+pull on dell: `cd ~/CascadeProjects/chaba && git commit
  --allow-empty -m x` → BLOCKED message; `CHABA_ROLE_COMMIT_OK=1` overrides.
- `CHABA_CHECKOUTS="$HOME/CascadeProjects/chaba*" bash scripts/check-single-writer.sh`
  — shows `role=` per checkout, warns on role-less master checkouts.
- Branch: `dispatch/20261022-125416-stale-non-served-clones-dell-c`
  (commit 7d2adb7e, not pushed — dispatch rule).
