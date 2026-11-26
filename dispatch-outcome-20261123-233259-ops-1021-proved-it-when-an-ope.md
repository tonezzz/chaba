# Dispatch outcome — opencode-retry-stale-worktree (OPS-1039)

## What changed

`scripts/board/runner-agent.py` — the "worktree already exists" hard
fail in the lane start path is now a three-way gate
(`_stale_worktree_gate`, called from `_start_opencode_lane` AND
`start_kk_mac_lane` — identical worktree lifecycle, same collision):

- **live `devin-task-<tid>` unit (or `-fuN` followup)** → defer with a
  reason that lands in the "start failed:" comms line. Checked FIRST —
  a stale `exit_code` from a prior attempt must not trick the GC.
- **provably-over previous run** → `git worktree remove --force` +
  `worktree prune`, then proceed to `worktree add -B` as before.
  "Provably over" = taskdir `exit_code`/`verdict.json` (the spec's
  finish evidence), OR lane-family `meta.json` executor
  (`opencode*`/`kk_mac_local`) with no live unit — which also covers
  SIGKILL/RuntimeMaxSec/failed-launch residue that writes no
  exit_code. Foreign executor or unattributable meta → defer.
- Removal resolves the owning repo from the tree's own
  `--git-common-dir` (action.repo can change between retries); a
  still-registered (locked) tree defers, unregistered dir residue is
  rmtree'd. Taskdir evidence is never touched.

New tests: `tests/board/test_runner_stale_worktree.py` — 12 cases,
real git worktrees in tmpdirs, unit/systemctl stubbed. Trail doc:
`docs/ssot/jobs/board/2026-11-23-runner-stale-worktree-gc.yml`.
Module docstring Worktree-GC paragraph updated.

## Root cause confirmed

`start_task` builds `runner-<cid>-<epoch>` truncated to 60 chars —
long card ids lose epoch digits, so tids collide across retries
(card spec's "deterministic per card" is truncation, not design).
Archived `diagnose-con01-dead-jobs-via-opencode-re-6da54c` shows the
same "worktree already exists" loop. The unit-name truncation itself
is unchanged (out of scope) — the GC makes the collision
self-healing.

## Verification

- `pytest tests/board/test_runner_stale_worktree.py` — 12/12 pass.
- Regression: test_worktree_gc + test_runner_agent_{lane,launchd,
  retry,reconcile} + test_executor_contract — 206 passed.
- `py_compile` clean; jobs YAML lints.

## Deploy note

Not pushed/merged (dispatch rails). On merge to master, hosts pick it
up via chaba-repo-sync; runner-agent `_self_update` installs the
differing repo copy on its next pass (mtime guard) — no manual scp.

lessons:
- runner-* unit names truncate `runner-<cid>-<epoch>` to 60 chars — long card ids collapse tids across retries; any per-tid resource (worktree, taskdir, unit) must tolerate collision.
- "worktree already exists" was a hard fail with no liveness/evidence check — lane start paths sharing dispatch-wt-<tid> need the same gate (opencode AND kk_mac both had it).
- taskdir finish evidence ordering matters: check unit liveness BEFORE trusting a stale exit_code from a prior attempt.
- Dead-without-evidence runs (RuntimeMaxSec/SIGKILL/failed rt_launch) leave no exit_code — lane-family meta.json + dead unit is the reapable signal, or timeout-killed runs still wedge retries.
