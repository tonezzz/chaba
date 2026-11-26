# dispatch outcome — sweep-pagination-offset-keyset-for-mddb-5afeca (attempt 2)

## What this run is

Re-dispatch of attempt 1 (`devin-task-20261125-210908-...`), which did the
full analysis + fix + live verification but **produced no commits** — the
worktree was left dirty and merge-sweep counted it a failed dispatch.
This run ports that verified work onto current master and commits it.

## What changed (same diff as attempt 1, rebased)

`scripts/ada/prune-old-docs.py` and `scripts/device-telemetry/prune.py`:

- `/v1/search` requests now send `sort: "key", asc: true` — the server
  default sort is `updatedAt`, which reshuffles on every write and made
  the offset window maximally unstable (the card's named bug).
- Page termination is now cap-aware: mddb 2.18.x caps `limit` at 1000
  (`X-Limit` header) while the scripts requested 5000 and stopped on
  `len(page) < 5000` — so every sweep was scanning only the first ~1000
  docs. (Bigger bug than the one the card named.)
- `prune-old-docs.py` also sends `filter: {<ts_key>: {"lt": <cutoff>}}`
  (MetaFilter, mddb ≥2.18) so enumeration touches only expired docs;
  2.15.x ignores the unknown field and the client-side check still
  applies. Deletes still go through `/delete-batch`.
- Both sweeps are wrapped in `MAX_PASSES=5` convergence passes — a pass
  that deleted >0 re-enumerates so docs skipped by mid-sweep foreign
  writes are caught the same run.
- `prune.py` keeps the newer CHUNK=100 / timeout=300 delete-batch tuning
  that landed on master after attempt 1's base (2026-11-26 timer-alert
  fix); the pagination changes were merged on top, not copied over it.

## API verification (from attempt 1, unchanged)

- `/v1/search` has **no keyset/cursor** in any deployed or current
  version (checked fork source + upstream v2.18.10/v2.19.13;
  `SearchRequest` = collection/filterMeta/filter/sort/asc/limit/offset).
- `POST /v1/documents:deleteWhere` (GO-045, ≥v2.18.8) IS a true keyset
  (filter + nextCursor + dryRun) and was verified live — but rejected
  for sweeps: per-doc write path ~0.5s+/doc vs delete-batch's
  single-transaction chunks.

## Re-verified this run

- `py_compile` clean on both scripts.
- `python3 scripts/device-telemetry/prune.py --dry-run` →
  `expired 8609, would delete 8609/22699 (>7d on key ts, 1 pass)` —
  scans all ~22.7k docs (pre-fix it stopped at ~1000).
- `python3 scripts/ada/prune-old-docs.py --dry-run --only ada-ha-events-dev`
  → clean on both bases (:11025 filter-ignored full scan, :11023
  filter honored).

## Deploy notes (unchanged from attempt 1)

- `prune-old-docs.py` lands via exec-checkout sync after merge.
- `device-telemetry/prune.py` runs an INSTALLED copy on idc03 —
  post-merge run `scripts/device-telemetry/install.sh prune` on idc03.
- host-logs :11026 has ~445k expired docs backlog from the cap bug;
  nightly runs drain it over days (faster one-off:
  `docs/kb/mddb-prune-compact.md`).

Trail: `docs/ssot/jobs/mddb/2026-11-26-sweep-pagination-keyset.yml`.

lessons:
- mddb 2.18.x caps /v1/search limit at 1000 (X-Limit header) — clients requesting more get silently truncated pages; terminate on len(page) < min(requested, X-Limit).
- /v1/search default sort is updatedAt (reshuffles per write); pass sort=key+asc for stable offset windows. No keyset/cursor exists even in 2.19.13.
- /v1/documents:deleteWhere (≥2.18.8) is a real keyset delete but ~0.5s+/doc — fine for targeted purges, wrong tool for bulk retention sweeps; /delete-batch single-tx chunks are far faster.
- MetaFilter `filter` field (lt/lte/gt/prefix) is ignored as unknown JSON on mddb <2.18 — safe to send unconditionally for graceful degradation.
- Dispatch attempt that leaves the worktree dirty produces NO commits and is scored a failed attempt even when the work is done — always `git commit` before ending.
