# dispatch-cleanup-unmerged-guard — outcome

## What changed

`scripts/devin/devin-precleanup-check.py` — `worktrees()` now ancestry-checks each
dispatch worktree, not just its dirty state:

- `worktree_branch()` resolves the ref to check: task `meta.branch` first (when it
  still resolves via `rev-parse --verify refs/heads/<branch>`), else the worktree's
  checked-out branch, else detached `HEAD`.
- `base_ref()` picks the repo's base: `master` → `main` → `origin/master` →
  `origin/main` (ada-pi worktrees have no `master`; previously they'd silently
  skip the check).
- `unmerged_commits()` runs `git log --format='%h %s' <base>..<ref>`; a non-empty
  list marks the row `unsafe`.
- Report additions: `branch` and `unmerged` columns in the Dispatch worktrees
  table, a "Stranded commits (not reachable from base branch)" section listing
  each commit, a top-level warning (`N dispatch worktrees hold commits not
  reachable from the base branch`), and `unmerged_worktrees` in the `--json`
  summary.

## Result

Verified live on tony-dell:

- Created `~/CascadeProjects/dispatch-wt-99999999-testunmerged` from a throwaway
  repo — CLEAN tree, branch `test-unmerged-branch` with 2 commits not on master.
- Ran the script (`--report-dir /tmp/wtguard-report --skip-integrity --db
  /tmp/wtguard-empty.db`). Report flagged the row `clean | test-unmerged-branch |
  2`, listed both commits under "Stranded commits", and emitted the warning.
- Pruned the test worktree (`git worktree remove`, branch deleted, repo removed) —
  this is exactly the silent-loss scenario from the card (a clean tree would have
  read as safe before this change).
- Real-world bonus: the run surfaced 11 pre-existing dispatch worktrees (chaba and
  ada-pi) holding commits not on their base branch — the guard already works on
  real data.

## How to verify

`python3 scripts/devin/devin-precleanup-check.py` — check the "Dispatch worktrees"
table for the `unmerged` column and the "Stranded commits" section in
`~/.local/share/devin/cleanup-reports/devin-precleanup-*-latest.md`.

## Trail

`docs/ssot/jobs/infrastructure/2026-10-05-precleanup-unmerged-guard.yml`

## Deferred (per card note, not in spec)

Card note also suggested emitting a focus-inbox/comms entry for stranded commits;
only the report output was implemented. A follow-up could push
`unmerged_worktrees > 0` findings into `docs/ssot/focus-inbox/`.
