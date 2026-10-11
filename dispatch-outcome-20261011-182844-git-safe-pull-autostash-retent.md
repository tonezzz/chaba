# dispatch 20261011-182844 — git-safe-pull autostash retention (card safe-pull-autostash-resurrection)

## What changed

`scripts/git-safe-pull.sh` (+117/-11) — both fixes from the card, plus two adjacent
correctness fixes in the same code path:

- **Drop superseded autostash after a fully-resolved pop** — `_resolve_autostash_pop`
  now tracks whether any conflicts were seen and whether all resolved. When every
  contested path was generated (resolved to HEAD) and no unmerged paths remain,
  `_drop_resolved_autostash` archives the entry's patch then `git stash drop`s it.
  Safety guards: only fires when `stash@{0}` differs from the pre-pull `refs/stash`
  tip (i.e. it is the entry this pull created) AND its message matches
  `autostash`/`Auto stash` — pre-existing or named stashes are never touched.
- **Periodic autostash GC >7d** — new `_gc_autostash` runs on every safe-pull
  invocation (dell's kanban-commit.timer hits it ~every 15min; satellites via
  git-safe-push). Autostash entries whose commit date exceeds
  `SAFE_PULL_AUTOSTASH_GC_DAYS` (default 7, `0` disables) are archived then dropped,
  highest index first so `stash@{n}` numbering never shifts under a pending target.
- **Patch archive** — `_archive_stash` writes `git stash show -p` to
  `SAFE_PULL_STASH_ARCHIVE` (default `~/.local/share/chaba-stash-archive/`, matching
  the manual GC convention) as `<stashdate>-stash-<n>-<sha8>-<why>.patch`. Archive
  failure blocks a GC drop (may hold real work) but not a resolved-pop drop
  (provably redundant).
- `_rebase_in_progress` now uses `git rev-parse --git-dir` — the old
  `.git/rebase-merge` check never fired in linked worktrees (.git is a file there),
  so conflicted rebases in dispatch worktrees stalled until a human found them.
- `_resolve_autostash_pop` handles modify/delete on generated paths
  (`git checkout HEAD` fails when upstream deleted the file → `git rm -qf`).

New trail doc: `docs/ssot/jobs/infrastructure/2026-10-11-git-safe-pull-autostash-retention.yml`.

## Why

Conflict-retained autostashes piled up per checkout (33 on dell) and were the
reservoir the resurrection waves drew from: a later pop 3-way-merged an ancient
card file — stale `column:` merges "cleanly" while upstream comms land at bottom —
flipping closed cards back to review (4 waves). The column guard (sibling card
git-autostash-column-guard) already fixes the merged worktree; this change removes
the stash pile that kept feeding it.

## Verified (scratch repo in /tmp, since cleaned up)

- pop conflict on `docs/ssot/` path → resolved to HEAD, autostash archived +
  dropped, pre-existing named stash untouched, exit 0
- pop conflict on non-generated path → stash retained + conflict left for manual
  merge (unchanged behavior)
- forged 40-day-old autostash → archived + GC'd; fresh autostash and named WIP
  stash kept; indices renumber correctly
- `SAFE_PULL_AUTOSTASH_GC_DAYS=0` → GC skipped
- mid-rebase generated conflict still resolves upstream-wins with
  `.local-conflict-*` preservation
- `git rev-parse --git-dir` rebase check verified detectable in a linked worktree
- `bash -n` clean; no real-repo state touched (worktree's own stash@{0} autostash
  left as-is)

## Notes / how to verify

- Changes are uncommitted in this worktree (dispatch rule: no commit to default
  branch, no push). Diff: `git diff scripts/git-safe-pull.sh`.
- On dell: after this lands, the next `kanban-commit.timer` pull runs GC; a
  conflicted-pop pull drops its own stash. Archive dir grows under
  `~/.local/share/chaba-stash-archive/` — same place Tony's manual GC put patches.
- Related: stash-graveyard-triage (manual audit of remaining non-autostash pile)
  stays open — GC only touches autostash-message entries.
