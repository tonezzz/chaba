# cms-cam-page-compaction — dispatch outcome

Branch: `dispatch/20261005-211715-cam-wall-cms-py-when-regenerat` (worktree only — not pushed, not deployed, not committed per dispatch rules)

## What changed

**`scripts/cam-wall/cam-wall-cms.py`** — page lifecycle, supersede-by-construction:

- Each run computes the canonical publish set (`camwall-<area>` wall pages, `cam-<zone|dev>-<slug>` cam pages, `cctv-walls`, conditional `dvr-wall`). Any doc this generator wrote that is absent from the set — legacy key forms (raw Thai-keyed slugs, old zone-scoped `cam-<zone>-*` keys, retired cams/zones) — gets `status:superseded` + `superseded_by` + `superseded_at` on both lang variants. **`mddb_delete` is gone entirely — nothing is ever deleted**; cam pages are operational history.
- Successor resolution maps old keys to their live replacement (`_cam_successor` handles cross-zone moves and ascii-normalized renames; falls back to the wall page, then `cctv-walls`). New pages carry `meta.supersedes` back to every key they replace — built from `superseded_by` back-links so there are no dangling links.
- **Retention pass** (`archive_superseded`, `ARCHIVE_DAYS = 7`): generated docs that are superseded AND whose content age (`meta.updated` — frozen at last publish; `updatedAt`/`addedAt` fallback) exceeds 7 days flip to `kind:archive` + `archived_at`. Still queryable in MDDB; gone from index weight.
- **`fresh_for` `"600"` → `"1h"`** — bare seconds never parsed in the index `stale()` (only h/d/m suffixes), so cam pages could never flag ⚠STALE.
- **Lane safety**: `_zone_sources()` boundary — a doc whose `zone:` sources don't intersect this lane's zones is never touched (dell vs VPS lanes share the collection + `generated_by` tag).
- **Revive**: a key back in the publish set is force-rewritten (hash dedup bypassed) → `status:active`, `kind:page`, lifecycle markers stripped.
- `--dry-run` flag: exercises the full lifecycle read path with zero writes (also suppresses notify state writes and detections trim).
- reports-index re-renders after the publish loop whenever supersede/archive marks changed.

**`scripts/lib/cms_index.py`** (new) — shared reports-index regen: paginated collection scan (old daily-brief render silently capped at 200 docs), kind gate (`report`|`page` only — `kind:archive` excluded by construction), `EXCLUDED_STATUS` (`superseded`, `archived`, `retracted`, `expired`), `fresh_for` TTL stale flag, one render for all writers.

**`scripts/report-daily-brief.py`** — `regen_reports_index()` delegates to `lib.cms_index` (was a private duplicate without the status filter or pagination); `written_by` stays `report-daily-brief.py`.

**`scripts/ada/cms-audit.py`** — `STUB_STATUS` gains `superseded` (skip A1 thin check on historical pages); new `DEAD_STATUS` set removes superseded/archived/retracted/expired docs from C1 duplicate-pair and C2 staleness warnings — they are *supposed* to be old and duplicated-ish.

**`tests/camwall/test_cam_wall_cms.py`** (new) — FakeMDDB transport covering empty-zone safety, the full lifecycle (supersede → 7d archive, zero deletes, supersedes links on canonical pages), index exclusion, `"1h"` stale flagging and `"600"` non-parsing.

## Result

- `python3 -m unittest discover -s tests/camwall -v` — **3/3 pass**
- `py_compile` clean on all touched files
- **Simulated live run** (real zone manifests + the real `ada-cms-pages` backup export served through FakeMDDB, full `main()` in-process): `walls: 8 pages + 38 cams + index ok · superseded 44 archived 0` — 88 lang-docs superseded in one sweep, **zero deletes**, reports-index contains no superseded/archived key, canonical pages carry `supersedes` to their legacy keys (e.g. `cam-burapha-bangna-trat-km-0-east` ← its raw Thai-keyed predecessor). `archived 0` is correct — nothing superseded had content >7d old in the backup snapshot.
- **Live `--dry-run` deferred**: MDDB (`100.74.146.0:11023`) refused connections at verify time (host pings, service down — it was reachable earlier in the session). Re-run `python3 scripts/cam-wall/cam-wall-cms.py --dry-run` post-merge.

## How to verify

1. `python3 -m unittest discover -s tests/camwall -v`
2. Post-merge first live run: one-time sweep superseding ~44 legacy keys (~88 docs); subsequent 15-min ticks should show `superseded 0 archived 0` in steady state — **cam-\* count stabilizes**.
3. `reports-index` contains only active `kind:page|report` rows; superseded docs still queryable via MDDB search/get.
4. Any generated doc superseded with `meta.updated` >7d old flips to `kind:archive` in the same run it gets superseded.
5. Index one-liners flag `⚠STALE` when a page's `fresh_for` TTL lapses (now possible — `"1h"` parses, `"600"` never did).

Known gap (documented in the jobs file): ada-pi's `tool_runner._cms_reports_index` still filters only by kind — superseded kind:page docs in their 7d window can surface via that path until ada-pi adopts the same `EXCLUDED_STATUS` gate. In-repo regens are clean.

SSOT trail: `docs/ssot/jobs/ada/2026-10-05-cam-cms-page-lifecycle.yml`

## Summary

cam-wall-cms.py now does supersede-by-construction: every generated page absent from the current publish set is marked status:superseded with a superseded_by link instead of being deleted, new pages carry meta.supersedes back-links, and superseded generated docs older than 7 days flip to kind:archive — queryable history that stays out of index weight. fresh_for moved to a parseable "1h" so the index can flag stale cam pages, a shared scripts/lib/cms_index.py now renders reports-index for both cam-wall-cms and report-daily-brief with superseded/archived/retracted/expired excluded, cms-audit skips dead-status docs for duplicate/staleness noise, and a revive path cleanly reactivates cams returning to the roster. Tests pass 3/3 and a full simulated live run against real manifests plus the collection backup superseded 44 legacy keys with zero deletes and a clean index; live --dry-run was deferred because MDDB refused connections at verify time.
