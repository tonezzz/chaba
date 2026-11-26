# Dispatch outcome — exec-sync-autostash-conflict-codefile

## What changed

`scripts/git-safe-pull.sh` — the autostash-pop conflict path no longer
leaves live conflict markers in non-generated code files, and the run
now fails loudly when manual merge intervention is required:

- New `_pop_resolve_to_head()`: for every unmerged path left by a
  failed autostash pop, preserves the stash side (stage 3, stage-2
  fallback) as `<path>.local-conflict-<ts>` then resets the worktree
  file to HEAD (`git rm` when upstream deleted it). Previously only
  card YAMLs got a sidecar and only generated paths were resolved;
  non-generated paths were "kept for manual merge" with `<<<<<<<`
  markers left in place — the 2026-11-09 timer-sentinel incident where
  a systemd job SyntaxError'd every tick while chaba-repo-sync
  reported `Result=success`.
- `_resolve_autostash_pop()` now resolves ALL contested paths through
  the helper, returns non-zero on non-generated conflicts, and the
  dead `CARD_POP_RE` was removed (every resolved path keeps a sidecar).
- New `_autostash_pending()`: detects a retained autostash entry created
  by this pull (pop conflict, untracked-restore failure, aborted rebase
  that never popped) and sets `PULL_NEEDS_MANUAL`, which exits 1 after
  the GC/tool-sync tail — covering silent pop failures that leave no
  unmerged paths.
- `chaba-repo-sync.service` runs the script directly and
  `git-safe-push.sh` already propagates exit 1, so the timer-alert
  surface now sees the manual-merge debt.

`tests/test-kanban-commit.sh` — new section M reproduces the incident:
dirty tracked `tool.py` + upstream v2 → pop conflict; asserts exit≠0,
no `<<<<<<<`/`=======`/`>>>>>>>` markers, `py_compile` passes,
`tool.py.local-conflict-*` holds the local edit, autostash retained,
HEAD contains upstream, no unmerged entries.

`docs/ssot/jobs/infrastructure/2026-11-25-git-safe-pull-autostash-codefile-fix.yml`
— job trail per dispatch rules.

## Result

- Commit `8f691c3074` on branch
  `dispatch/20261125-020433-goal-prevent-git-safe-pull-aut` (not pushed,
  per dispatch rules).
- `bash tests/test-kanban-commit.sh`: all 9 section-M checks pass with
  the fix; the key checks FAIL on the unmodified script (markers left,
  no sidecar, exit 0) — the test detects the bug.
- Sections I/J (6 checks) fail IDENTICALLY before and after the change —
  pre-existing fixture/environment drift in the merge-fallback cases,
  unrelated to this fix.
- Done-condition met: simulated autostash conflict on a non-generated
  code file leaves no live markers and no SyntaxError; the sync exits
  non-zero when manual merge is required.

## How to verify

```
bash tests/test-kanban-commit.sh   # section M: 9/9 ok
bash -n scripts/git-safe-pull.sh
```

On a real exec checkout, the next conflicted pop will: reset the file
to HEAD, drop `<path>.local-conflict-<ts>` sidecars, keep the autostash
entry, print the non-generated-path warning to the journal, and exit 1
→ `systemctl --user status chaba-repo-sync.service` shows failure +
timer-alert card fires.

## Notes / side effects

- Generated NON-card pop conflicts now also leave `.local-conflict-*`
  sidecars (previously the local side was dropped silently);
  `reconcile-local-conflicts.py` flags strays under `docs/ssot` on the
  ops-local-conflict-guard card — intended "nothing silently lost"
  behavior.
- Sidecars outside `docs/ssot` (e.g. `scripts/*.py.local-conflict-*`)
  are kept on disk and named in stderr + the retained stash; the
  reconciler does not scan there — exit-1 + timer-alert is the
  surfacing for those.

lessons:
- `nf()` subshells swallow variable assignments — propagate status via `cmd || FLAG=1`, never via vars set inside.
- tests/test-kanban-commit.sh sections I/J were already failing before this change (merge-fallback fixture drift) — verify pre-existing failures against HEAD before assuming a regression.
- aut stash pop stage semantics: stage 3 = stash side, stage 2 = HEAD side; `git checkout HEAD -- <path>` clears unmerged index entries.
- `_drop_resolved_autostash` only fires when zero paths remain unmerged AND bad=0 — keep bad=1 for anything needing human review or the safety stash gets dropped.
