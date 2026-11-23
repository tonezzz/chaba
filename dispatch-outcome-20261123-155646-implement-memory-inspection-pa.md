# Dispatch outcome — memory-inspect-pages (MEM-0745, attempt 3)

## What changed

Branch `dispatch/20261123-155646-implement-memory-inspection-pa`, 2 commits:

- `b12887a4b5b` — cherry-pick of `df2f40c5c0` (the live-verified tony-omen
  implementation from dispatch/20261123-145030, fetched from origin):
  - `scripts/ada/bank-inspect.py` — per-lane snapshots of every
    `ada-ha-bank-*` visible to each persona lane's instance on the memory
    plane (:11023) → `memory-inspect` index + `memory-inspect-<bank>`
    leaf pages in that lane's CMS collection (:11027). Lanes resolved
    from `ssot.apps.ada-persona-lanes.yml` (tony→ada-cms-pages,
    kk→-kk, michael→-mn, kk-dev→-kk-dev, ro mounts flagged ro).
    Secret-keyed/secret-shaped entries redacted at write time.
  - `apps/cms-render/server.py` — `memory-inspect` render kind +
    `ada-cms-pages-mn`/`-kk-dev` collections.
  - `apps/cms-render/templates/memory-inspect.html`,
    `ssot.jobs.yml` daily job on tony_dell 05:40, rendered units,
    `tests/ada/test_bank_inspect.py` (12 tests), detect-kind cases.
- `1f496e22609` — layered improvements salvaged from the dead colossal-moat
  checkpoint (dispatch/20261123-145907): pages now publish
  `kind=memory-inspect` (was kind=report — keeps snapshots out of
  report-distill sweeps); detect_kind matches kind OR key prefix;
  index_rows groups them under a new **Memory** section; `cms_index.py`
  whitelists the kind; template gains the read-only banner; runbook
  updated (`docs/ssot/jobs/ada/2026-11-23-memory-inspect-pages.yml`).

## Prior-failure analysis

Attempt 1 (tony-omen 14:50) completed and live-verified but its branch
never merged (auto-merge conflict-resolution failure). Attempt 2
(tony-dell 14:59, colossal-moat) re-implemented a variant, got 5 files
checkpointed + the rest uncommitted, then died on provider rate-limit
(exit=1, 23min). This run cherry-picked the verified commit and salvaged
the worthwhile bits of the partial rerun instead of re-implementing a
third time.

## Verification

- `pytest tests/ada/` — 311 passed, 1 skipped (cms_render needs fastapi)
- `pytest tests/ada/test_cms_render.py` in a venv with
  apps/cms-render/requirements.txt — 23 passed (incl. new
  memory-inspect page/listing/section cases)
- Merge-gate set (dispatch_repos REPO_TESTS["chaba"]) — 231 passed
- `render-jobs.py --check` — 117 jobs OK
- **Live snapshot on tony-dell**: `python3 scripts/ada/bank-inspect.py`
  wrote 37 pages — tony→ada-cms-pages 15, kk→ada-cms-pages-kk 8,
  kk-dev→ada-cms-pages-kk-dev 9, michael→ada-cms-pages-mn 5; exit 0,
  zero publish failures.
- Spot-check via MDDB :11027 confirms new meta
  (kind=memory-inspect, report_role=leaf, lane=tony).
- Live render: `http://100.102.134.91:8010/p/memory-inspect` → 200
  ("Memory inspect — tony lane"), `/p/memory-inspect-devin` → 200.
  (Deployed cms-render still runs old code → falls back to page template;
  the kind dispatch + Memory section activate on next deploy.)
- Cleanup: stale `memory-inspect-devin-tony`/`-developer-tony` pages
  from the dead attempt superseded live (status=superseded + pointer).

## How to verify

`python3 scripts/ada/bank-inspect.py --dry-run --lane tony` (worktree);
open `http://100.102.134.91:8010/p/memory-inspect`; after merge +
chaba-repo-sync on tony-dell, `render-jobs.py --host tony_dell
--ids bank-inspect --install` arms the daily 05:40 timer.

## Not done (needs merge/deploy, out of dispatch scope)

- Push/merge to master; unit install on tony-dell; cms-render restart
  on idc03 to pick up the new kind/template/Memory section.

lessons:
- A failed dispatch's branch may still be fetchable — `git fetch origin
  dispatch/<ts>-<slug>` recovers committed work even when the origin
  branch was never merged; check `git worktree list` for sibling
  worktrees holding uncommitted leftovers before re-implementing.
- MDDB /search caps at 1000 docs — a prefix filter on `key` returns
  nothing; verify writes by scanning a full-collection dump, not by
  filter queries.
- Publishing snapshot pages with kind=report puts them in reach of
  kind=report sweeps (report-distill); a dedicated kind plus an
  index_rows whitelist is the safer shape.
- cms_render tests skip silently without fastapi — a throwaway
  `.venv-test` + apps/cms-render/requirements.txt runs all 23.
