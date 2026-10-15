# dispatch-worktree-gc — worktree GC at card close + merge-sweep salvage

Card: `dispatch-worktree-gc` (OPS-0445). Runner: idc03.
Commit: `c13ca9fe4` on `dispatch/20261015-100100-in-scripts-board-runner-agent-`.

## What changed

Dispatch worktrees + `dispatch/<id>` branches accumulated forever (the
2026-10-11 tony-dell 97%→87% disk incident); the weekly
`devin-dispatch-prune.sh` remains the backstop, this adds prompt
removal at the two places a merge is proven:

- **`scripts/board/dispatch_repos.py`** — new `gc_worktree(worktree,
  merged_into, branch, task_id)`: removes the session worktree only when
  `git status --porcelain` is empty, no `devin-task-<tid>*` unit is
  active, and HEAD is an ancestor of `merged_into` (the pushed merge sha
  or a fetched `origin/<base>` — the caller's merge proof). Plain
  `git worktree remove` (never `--force` — git re-refuses dirty/locked
  trees); branch via `-d` with an ancestry-gated `-D` fallback
  (prune.sh semantics). New `gc_session(res)` maps a `close_out()`
  result to GC + one-line comms notes, self-gating on ancestry so
  conflicted/unmerged results just skip (`"worktree kept: <why>"` note).
  `KANBAN_WTGC=0` disables.
- **`scripts/board/runner-agent.py`** — `close_out_merge` now appends
  `gc_session` notes after `close_out` (getattr-guarded for stale host
  checkouts of dispatch_repos). The card-close path.
- **`scripts/board/kanban-dispatch.py`** — same hook in
  `merge_pending_one` (dell's local close path), GC outside the card
  lock, comms inside.
- **`scripts/board/merge-sweep.py`** — new `REMOTE_GC_PROBE` (ships over
  `ssh <runner> python3 -`, same transport as the session probe) +
  `gc_runner_worktree()`, called after a successful `merge_strict` push
  and at the already-ancestor checks. The runner removes its tree only
  when clean and every commit is inside the sha dell merged/pushed —
  unreachable runners retry next pass, removals post a one-line card
  comms ("merge-sweep GC: removed worktree …, branch … on <host>").
- **`tests/board/test_worktree_gc.py`** — 16 cases; **`docs/ssot/jobs/
  workflow/2026-10-15-dispatch-worktree-gc.yml`** — decision trail.

## Verify

`python3 -m unittest discover -s tests/board` → 141 tests, all green
(2 skipped, pre-existing pytest-absent). Covers the card's acceptance:
merged+clean → worktree + branch removed (`test_runner_agent_close_out_
merges_and_gcs` runs the real close path end-to-end: merge → push → wt
gone → comms note); dirty → preserved; unmerged → preserved; locked →
preserved; sweep comms note lands via the locked-YAML fallback. A real
live-card close wasn't exercised (no board mutation/push from this
session) — the first production close or merge-sweep pass will post the
"worktree GC: removed …" comms line; grep comms or watch
`devin-dispatch-prune` no longer being the only remover.
