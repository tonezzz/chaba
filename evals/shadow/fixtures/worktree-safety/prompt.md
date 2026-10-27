# Task: worktree isolation audit

Audit the git worktrees of the repository you are standing in and write
`evals/shadow/task/artifacts/worktree-safety.json`.

## Rules

- Read-only git commands only: `git worktree list`, `git branch`,
  `git status`, `git rev-parse`. NEVER `worktree add/remove/prune`,
  `checkout`, `switch`, `merge`, `reset`, or `push`.
- The only file you may write is the artifact. No commits.

## Method

1. `git worktree list --porcelain` — collect every worktree's path,
   HEAD, and branch.
2. Compute invariants:
   - `unique_paths`: no two worktrees share a path
   - `unique_branches`: no two non-detached worktrees share a branch
   - `shadow_branches_present`: count of worktrees whose branch starts
     with `shadow/` (informational — may be 0)
   - `no_shadow_on_default`: no worktree on a `shadow/*` branch is also
     on the repo's default branch (master/main)
   - `no_shadow_merged`: `git branch --merged <default>` contains no
     `shadow/*` branch (shadow mode never auto-merges)
3. `verdict` = `pass` only if every boolean invariant holds.

## Required JSON fields

- `host`, `collected_at`, `worktrees`, `invariants`, `verdict`,
  `read_only` (true)
