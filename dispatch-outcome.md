# dispatch outcome — ha-michael-worktree-sync

## What was done

Reconciled the HA/michael-lane dispatch sprawl (chaba + sunsynk-power-flow-card)
with origin/master.

### chaba (origin/master 8182733f → 69807c91)

- **Merged 6 diverged branches** holding real unmerged session work:
  traffic-snap shim (123304), flood-news CMS + normalization (123308),
  tony-ha ada-voice-card speaker-ws fix (124438), cms-generator schedule
  audit (130242), gev-gemini tools/live checks (130841), and the
  gev-auto-health probe (131449 — its files were left **uncommitted**;
  committed as db2d0fdf before merging).
- **Archived 4 patch-merged dead branches** as `archive/20261005-*` tags
  (pushed) — their real work was already on master; only
  `dispatch-outcome.md` scratch remained.
- **Removed 15 dead worktrees + deleted 15 branches.** Remaining worktrees:
  this session, a duplicate dispatch of this card (132452, left alone —
  possibly live), and a new dispatch (133043).
- Merge method: plumbing only (`merge-tree --write-tree` + `commit-tree` +
  `push <commit>:master`) — live checkout at `~/CascadeProjects/chaba` never
  touched; local master stays 4-behind as before, plain `git pull` fixes.
- One merge needed a manual union (`ssot.jobs.yml` kanban-sync note —
  master's `on_failure` text + branch's gev-auto-health mention), pushed as
  fix commit 69807c91.

### sunsynk-power-flow-card

- `sunsynk` is 1 ahead of origin/main (a84b9b6 battery 3/4); orphan
  `dispatch/20261004-204448-*` holds an additional e52346e — left for Tony.
- **Live checkout is dirty with ~24-file battery-3/4 WIP** differing from
  e52346e (probably a newer iteration). Snapshotted non-destructively to
  `wip/bat34-uncommitted-snapshot-20261005` (5befc79 via `git stash
  create`); worktree untouched, nothing lost if it's abandoned.

### Out-of-scope lanes (inventoried in the manifest, not acted on)

- ada-pi: 4 merged worktrees removable; 2 diverged dead-session branches
  with real tool-merge work (memory 8→4, camera).
- mddb-fork: prunable `~/mddb-bench/stock-src` registration.

## Deliverables

- `docs/ssot/audit/ha-michael-worktree-sync-20261005.md` — full manifest.
- `docs/ssot/jobs/infrastructure/2026-10-05-ha-michael-worktree-sync.yml` —
  job record.

## Verify

- `git -C ~/CascadeProjects/chaba fetch && git log --oneline origin/master -8`
  → merge commits 67e110db…93d98ec6 + 19612282 + 69807c91 on top.
- `git worktree list` → main + 3 live dispatch worktrees only.
- `git tag -l 'archive/*'` → 4 archive tags.
- `git -C ~/CascadeProjects/sunsynk-power-flow-card branch | grep wip` →
  snapshot branch present; `git status` there still shows the 24 dirty files.

## Notes for operator

- Decide the sunsynk bat34 lineage (e52346e vs wip-snapshot) — it's the only
  remaining HA-lane divergence, and it needs build+typecheck before deploy.
- `dispatch-outcome.md` conflicts on literally every merge of a dispatch
  branch — worth gitignoring repo-wide.
