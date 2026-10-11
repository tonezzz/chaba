# Dispatch outcome — dispatch-gitignore-shadow-guard (OPS-0427)

Pre-merge guard added to all dispatch merge paths: incoming-branch
additions that are symlinks, or files whose names are ignored only as
directories (trailing-slash `.gitignore` patterns — the 2026-10-10
`.venv` incident class), now hold the merge before it reaches origin.

## What changed

- `scripts/board/dispatch_repos.py`
  - new `shadow_paths(repo, base, head, cwd)` — `git diff --raw -z
    --diff-filter=A` for net additions; mode `120000` → flag as
    symlink; everything else probed via one batched
    `git check-ignore -v -n --no-index --stdin` of `P` + `P/`, flagging
    when `P/` matches a `/`-terminated pattern while `P` is trackable.
    check-ignore runs in `cwd` (merged worktree on merge paths, session
    worktree for the board-api note). Symlink entries are never probed —
    `check-ignore P/` on a symlink is FATAL and kills the batch.
  - `_merge_and_gate` gains the base arg + a shadow check between the
    clean merge and the test gate → close_out returns `shadows=[...]`,
    merged=False; the branch is still pushed so work isn't stranded.
  - `close_out_notes` reports the held merge with the shadow paths.
  - `dr.guard` (board-api merge guard) appends shadow paths to its
    unmerged-commits note on review→done attempts.
- `scripts/board/merge-sweep.py` — `merge_strict` flags shadows
  post-merge/pre-push; `sweep_card` posts one comms entry listing the
  paths and stamps `action.sweep.shadow_blocked = head[:12]` so a
  flagged head isn't re-merged every pass while a fixed branch
  re-checks from scratch.
- `scripts/board/kanban-dispatch.py`, `scripts/board/runner-agent.py` —
  `res["shadows"]` joins the held-merge condition (same lane as
  conflicts/test_failures/goals): verified=False + informed auto-retry.
- `scripts/stack-preflight.py` — warn-only lint: a state dir's
  `.gitignore` single-segment `X/` pattern with no bare `X`/`/X`
  counterpart warns "add bare X".
- Tests: 3 new in `test_merge_sweep.py` (symlink block, dir-pattern
  file block, head-keyed re-merge after fix), 3 new in
  `test_dispatch_close_out.py` (symlink hold + guard note, dir-pattern
  hold, direct detector unit test).
- SSOT trail: `docs/ssot/jobs/kanban/2026-10-11-gitignore-shadow-guard.yml`.

## Result

`python3 -m unittest discover -s tests` — 220 tests, 0 failures.
Manual repro (spec verify): scratch repo + dispatch worktree branch
adding a `.venv` symlink over a `.venv/`-only .gitignore →
`dr.close_out` returns `merged=False`, `shadows=['.venv (symlink)']`,
branch pushed to origin, origin/master does NOT contain `.venv`.

## How to verify

- `python3 -m unittest discover -s tests/board` — the shadow tests
  build bare-origin + served + runner-worktree fixtures and run the
  real `sweep_card`/`close_out` paths.
- Manual: `dispatch_repos.shadow_paths(<repo>, <base>, <head>)` on any
  branch that adds a symlink or a dir-shadowed name returns the
  annotated flag list.
