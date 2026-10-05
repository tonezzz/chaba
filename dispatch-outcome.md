# dispatch outcome — kanban-stats-node (kanban L2 report node)

## What was done

Implemented the `kanban` L2-domain node declared in the card spec:

- **`scripts/board/kanban-stats.py`** (new) — reads `docs/ssot/kanban/cards/*.yml`
  and computes: counts by column, action.status breakdown, open requests,
  cards-touched-24h, dispatch throughput last 7d (dispatched/finished/failed,
  per-day rate, median dispatch→finish cycle), stale-in-review >48h. Emits
  `reports/kanban/meta.yml` via `scripts/lib/report.py::write_meta()` +
  `append_timeline`, a rolling `reports/kanban/kanban-stats.yml` artifact, and a
  markdown rollup at `stacks/web/public/apps/system-report/data/kanban.md`.
  Outputs mirror into the served `chaba-tony-dell` checkout (dual-root pattern,
  same as report-system.py). Status = `delta` on stale-review or 7d dispatch
  failures, else `ok`.
- **`docs/ssot/infrastructure/ssot.reports.yml`** — `kanban` node registered
  (L2-domain, cadence `15m`, meta `reports/kanban/meta.yml`, refs
  ssot.kanban.yml) and added to `system-report` children.
- **`scripts/ada/kanban-sync.sh`** — runs kanban-stats.py each 15-min tick with
  `--cards-dir` pointed at the live served-checkout cards (fresher than the
  worktree's committed copies; read-only).
- **`docs/ssot/kanban/ssot.kanban.yml`** — `kanban-stats` ops lane documented.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — kanban-sync job note updated.
- **`docs/ssot/jobs/kanban/2026-10-05-kanban-stats-node.yml`** — job trail.

## Result

Verified working: live run wrote meta/stats/md in this worktree AND mirrored to
`chaba-tony-dell`; `report-system.py --print` renders `### kanban` as **OK**
("122 cards (doing 6, review 10); 4 open req; 0 stale-review; 17 done/7d").
`node scripts/ssot-validate-all.mjs` — 1137 files, 0 errors.

Note: the generator goes live on the next `kanban-sync.timer` tick after this
branch merges and the chaba-kanban-sync worktree ff-pulls (≤15 min).

## How to verify

    python3 scripts/board/kanban-stats.py --check    # stats + md, no writes
    python3 scripts/report-system.py --print | grep -A8 '### kanban'
    ls stacks/web/public/apps/system-report/data/kanban.md

Commit: `a52334d1` on `dispatch/20261005-105130-new-node-kanban-in-ssot-report`.
