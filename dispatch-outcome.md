# dispatch outcome — dispatch-merge-guard

## What was done

Closed the two dispatch-loop failure modes from the card:

**(a) canonical worktree base.** `devin-dispatch` now resolves a
per-repo `default_branch` and cuts worktrees from
`origin/<default_branch>` — never the checkout's current branch. The
repo whitelist moved to `$DISPATCH_DIR/repos.conf`
(`~/.local/share/devin-dispatch/repos.conf`; versioned copy
`scripts/devin/dispatch-repos.conf`; built-in fallback table in the
script for hosts without the file). `cmd_start` does a best-effort
`git fetch origin <branch>` first, falls back to a local `<default>`
ref with a warning, and fails loudly if neither exists. `meta.json`
now records `default_branch` and `base`. Applied to both
`scripts/devin/devin-dispatch.sh` and live `~/.local/bin/devin-dispatch`.
(Note: the card said "REPOS map in ~/.local/share/devin-dispatch" — it
actually lived inline in `~/.local/bin/devin-dispatch`; the new
repos.conf makes the spec's location literally true.)

**(b) review→done merge guard.** New `scripts/board/dispatch_repos.py`
resolves the card's `action.task_id` → meta.json → worktree/branch/
head/default-branch (with fallbacks for pre-change meta and deleted
worktrees) and checks `git merge-base --is-ancestor <head>
origin/<default>` in the target repo. `board-api.py`
`apply_merge_guard()` gates `close` and `move→done`: a non-ancestor
session head returns "blocked — unmerged commits remain on <branch>
(N not in <base>)", appends the comms entry, and leaves the card in
review. Passed/skipped guards append a note (incl. leftover dirty file
count); guard errors log-and-allow so the board never wedges.

**(c) dirty-worktree comms at session end.** `kanban-dispatch.py`
`poll_one` now calls `session_end_notes()`: posts "worktree <name>
dirty — N uncommitted file(s)" and, when applicable, "N commit(s) on
dispatch/<id> not in origin/<branch> — close will block until merged".

## Where

- `scripts/board/dispatch_repos.py` (new), `scripts/board/board-api.py`,
  `scripts/board/kanban-dispatch.py`, `scripts/devin/devin-dispatch.sh`,
  `scripts/devin/dispatch-repos.conf` (new)
- Live: `~/.local/bin/devin-dispatch`,
  `~/.local/share/devin-dispatch/repos.conf`
- Docs: `docs/ssot/kanban/ssot.kanban.yml` (execution section),
  `docs/ssot/jobs/infrastructure/2026-10-05-dispatch-merge-guard.yml`

## Verify

- Real dispatch on `sunsynk-card` (checkout parked on stale `sunsynk`
  branch): worktree HEAD == `origin/main` (b41ffcc), not `sunsynk`
  (a84b9b6); meta.json has `default_branch: main`, `base: origin/main`.
- Close gate e2e (worktree board-api on test port, real dispatch
  metadata): `POST /action do=close` → "blocked — unmerged commits
  remain on dispatch/<id> (1 not in origin/main)", card stays in
  review; `move→done` blocked likewise; after merging the branch →
  close succeeds with "merge guard: ... merged into origin/master;
  worktree still dirty: 1 uncommitted file(s)". Deleted-worktree and
  unresolvable-session fallbacks verified.
- `session_end_notes` on a dirty+unmerged worktree produced both comms
  lines via `poll_one`.
- `bash -n`, `py_compile`, `board-api --selftest` all pass.

## Not done / notes

- Board-side guards go live when this merges to master and
  `chaba-tony-dell` syncs (board-api.service + kanban-dispatch.timer
  run from that checkout). The `devin-dispatch` + repos.conf changes
  are already live.
- Guard checks only the card's latest `task_id`; orphaned earlier
  dispatch branches remain `devin-precleanup-check.py` /
  `dispatch-cleanup-unmerged-guard` territory.
- Dirty worktrees warn but never block close (spec: comms entry only).
