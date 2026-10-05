# HA/Michael worktree sync — 2026-10-05

Card: `ha-michael-worktree-sync`. Session: `dispatch-wt-20261005-132701`.
Scope: dispatch-whitelisted repos in the HA/michael lanes — **chaba**
(HA/michael stacks + ops SSOT) and **sunsynk-power-flow-card** (the HA card).
ada-pi and mddb-fork are the Ada/memory lanes — inventoried, not touched.

## chaba — 16 dispatch worktrees at audit time

origin/master moved `8182733f → 69807c91` (7 commits pushed by this session).

### merged → origin/master (real unmerged work), worktree+branch removed

| branch | content | merge commit |
|---|---|---|
| 123304-implement-a-traffic-camera-int | `stacks/services/traffic-cam/` traffic-snap shim (+999) | 67e110db |
| 123308-build-an-automation-tool-to-fe | flood-news CMS automation + memory-schema normalization (+4459) | 471d6eaa |
| 124438-investigate-why-ada-enroll-spe | `stacks/tony-dell/tony-ha/www/ada-voice-card.js` speaker-ws fix + job record | 6d78f3eb |
| 130242-enumerate-scripts-ada-py-that- | cms-generator schedule audit + systemd units | 49dd1b2a |
| 130841-chaba-stacks-tony-dell-gev-gem | gev-gemini tools-check.mjs + live-check.py + README | 93d98ec6 |
| 131449-new-chaba-probe-script-mirrori | gev-auto-health.py probe + 2 gev-auto-* cards — **uncommitted work recovered** as db2d0fdf first | 19612282 (+ fix 69807c91) |

All merges were conflict-free except `dispatch-outcome.md` (resolved to
master's copy — session scratch, superseded by job ymls/card comms) and, for
131449, `ssot.jobs.yml` (union-resolved in follow-up 69807c91).

### patch-merged dead — archived `archive/*`, worktree+branch removed

Real work already on master via other commits (`git cherry` `-`); remainder
was only `dispatch-outcome.md` / stale `ssot.kanban.yml` scratch.

- `archive/20261005-105032-in-scripts-board-kanban-dispat` (de787350)
- `archive/20261005-105130-new-node-kanban-in-ssot-report` (04699aa5)
- `archive/20261005-105816-scripts-render-board-py-add-a-` (022cad43)
- `archive/20261005-110419-new-reports-node-daily-brief-l` (36341320)

### fully merged dead — worktree+branch removed (no archive needed)

122613-ada-enroll, 122644-traffic-cam, 122651-automation-tool,
125644-render-board, 130445-devin-preclea (all 0 ahead of origin/master).

### left alone

- `132452-reconcile-ha-michael-related-w` — duplicate dispatch of this same
  card (queued 3 min before this session); possibly still live.
- `132701-reconcile-ha-michael-related-w` — this session.
- `133043-two-options-pick-one-in-spec-p` — new dispatch that started during
  this session.
- `master` checkout at `~/CascadeProjects/chaba` — was already 4 behind
  origin/master; untouched, plain `git pull` fast-forwards it.

## sunsynk-power-flow-card (HA card repo)

- `sunsynk` (live checkout branch): 1 commit ahead of origin/main —
  `a84b9b6 feat: add battery 3 and 4 support`. Not merged: origin's
  default is `main` and promotion is an explicit decision.
- `dispatch/20261004-204448-add-batteries-3-and-4-to-the-s`: orphan branch
  (worktree already gone) holding `e52346e` — "complete battery 3/4
  support in compact card and editor" — NOT on `sunsynk`. Left intact;
  the live-checkout WIP below may supersede it.
- **Live checkout is dirty with large uncommitted battery-3/4 WIP**
  (24 files, incl. `bat-elements.ts` ~1991-line delta, full-card, grid,
  inverter, load, pv, auxload, style, dto). Differs from e52346e — likely
  a newer iteration. Snapshotted non-destructively to branch
  **`wip/bat34-uncommitted-snapshot-20261005`** (5befc79, via
  `git stash create`; worktree untouched). Needs Tony: land e52346e then
  rebase WIP, or verify+land the WIP snapshot — plus `npm run build` /
  `tsc --noEmit` before deploy.

## ada-pi (Ada lane — inventory only, not acted on)

- 4 dispatch worktrees, all branches fully merged → removable any time:
  100603-cms-tool-group, 105014-cms-first-answers, 122233-tts-output-leaks,
  122438-calendar-plan.
- 2 diverged branches, no worktree, real unmerged work:
  `dispatch/20261004-210440-merge-the-memory-tool-group-8-` (1 commit,
  tools 8→4 merge) and `dispatch/20261005-004926-merge-the-camera-tool-group-5-`
  (1 commit, camera tool merge, "recovered uncommitted dispatch work").

## mddb-fork (memory lane — inventory only)

- `/home/tony/mddb-bench/stock-src` — detached worktree, flagged `prunable`
  by git. `git worktree prune` clears the registration.
- Main checkout on `feat/vector-algorithms` — active dev branch, untouched.
