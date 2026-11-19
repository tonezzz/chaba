# Dispatch outcome — cms-to-wiki-storage-assessment — 2026-11-19

## Result: measured assessment delivered — recommend Scenario A (retention+compaction), NOT migration

Deliverable: `docs/reports/2026-11-19-cms-to-wiki-storage-assessment.md` (this
worktree). No production changes made — all measurements were read-only
(REST + ssh inspection on idc03).

## What was found (all measured 2026-11-19)

- **idc03 disk is at 93% (23G free) and tonight's mddb-cms backup FAILED
  ENOSPC** — `mddb-backup.service` in failed state, last good cms gz is
  2026-11-18.
- **67G of stale pre-compaction rollback files** sit in the three mddb
  data dirs (cms 24G, ops 31G, leader 12G) — reclaimable with three `rm`s,
  no migration needed.
- **All live CMS content is ~41MB** (mddb-cms, measured via /v1/export:
  infrastructure-ssot 32MB derived index, ada-cms-pages 5MB, chaba-lessons
  2MB) inside a **22G db file** — ~98% is revisions (137k on 10k docs),
  meta-indices, and bbolt freelist. The file regrew 2.4G→22G (~3.3G/day)
  in the 6 days since the 11-13 compaction.
- **WP boards total movable content ≈ ~10MB** (news 3,962 items is a feed,
  not movable; lesson archive already in wiki). Wiki = 253 pages total.
- **No `maxRevisions` on any cms or ops collection**; ada-cms-pages alone
  gains ~17k revisions/day from hourly regen + 10–15min cam-wall/digest
  writers.
- **Ops host-logs retention is broken again**: `prune-old-docs.service`
  logs `host-logs: list failed — timed out` on :11026 daily; 423k docs,
  file regrew to 29G in 8 days post-compaction.
- Reconciled prior work: Education: 177 pages + Reports: 17 on the wiki;
  `WIKI_EDUCATION_WRITE=wiki` on; WP lesson CPT frozen (137 posts, 7.6MB);
  mddb-cms compaction verified but benefits were transient.

## Recommendation (in report)

Phase 0: delete the 3 stale rollback files (+67G, unblocks backups — needs
Tony approval). Phase 1: maxRevisions + truncate on cms collections.
Phase 2: repair host-logs retention (backup→scratch→delete-batch or
truncate). Phase 3: recurring size-triggered compaction cadence. Optional
Phase 4: ~10 authored reports → wiki as a consolidation pilot (storage
delta ≈ 0). Scenarios B/C rejected on measured bytes: moving everything
movable reclaims ~0 because bbolt doesn't shrink and content is a
rounding error vs. churn overhead.

## Verify

```
ssh idc03 'df -h /; du -sh ~/.config/containers/mddb*/data'
curl -s http://100.102.134.91:11027/v1/stats | python3 -m json.tool | head -30
ssh idc03 'journalctl --user -u mddb-backup.service --since "2026-11-19" --no-pager | tail -10'
```

lessons:
- mddb `/v1/export` is POST-only (`{"collection":"<c>"}`); GET returns {"error":"EOF"}.
- boards WP REST: `/wp-json/wp/v2/<cpt>` needs plural routes for built-ins (posts/pages/media) and `index.php?rest_route=` style on this vhost; `status=any` gives totals incl. private via X-WP-Total.
- bbolt compaction wins are transient without maxRevisions: cms db regrew 2.4G→22G in 6 days (~17k revs/day on ada-cms-pages alone); always check for stale `mddb.db.pre-compact*` rollback files — 67G were sitting there.
- prune-old-docs.py still silently fails on ops host-logs (`list failed — timed out`); journalctl the service, don't trust the timer ticking.
- Wiki API canonical path is root `/api.php` per ssot.mediawiki-news.yml; `WIKI_HOST=.../v0` in wiki-h3-gizmo.env is stale/misleading.
