# CMS → Wiki residual storage assessment — 2026-11-19

Card: `cms-to-wiki-storage-assessment` (KNB-0232). Read-only assessment; no
migrations, deletions, or writer changes were made. All sizes below were
measured live on 2026-11-19 (UTC+7) unless noted.

## Verdict (measured)

Moving remaining CMS content to Wiki would reclaim **≈ 0 meaningful bytes**.
Every movable store measured is tens of megabytes; the actual storage problem
on idc03 is **bbolt file growth (freelist + unbounded revisions) plus 67G of
stale pre-compaction rollback files**, none of which any content migration
touches. Recommendation: **Scenario A** — retention + compaction hygiene —
with an optional Scenario-B housekeeping pilot for a handful of truly
authored docs only if Tony wants surface consolidation for its own sake.

## Headline numbers

| Store | Live file | Stale rollback file | Content bytes (measured) |
|---|---|---|---|
| idc03 `/` (290G) | 268G used / 23G free (93%) | — | — |
| mddb (leader :11023) | 5.3G (+226M binlog) | **12G** `mddb.db.pre-compact-20261113` | 27,851 docs (ada-ha-*) |
| mddb-cms (:11027) | **22G** | **24G** `mddb.db.pre-compact` | **~41MB** export, 10,002 docs |
| mddb-ops (:11026) | **29G** | **31G** `mddb.db.precompact-20261111` | 433,389 docs telemetry |
| mddb-embed | 2.8G | — | vector index |
| `~/mddb-backups` | 19G | — | ~2 days of gz sets |
| `~/var/cache/devnest` | 33G | — | DevNest job caches (not CMS) |
| WP boards (Plesk) | n/a (shared host) | — | **~35MB** across all CPTs |
| Wiki (MediaWiki 1.46.2, Plesk) | n/a | — | 253 pages / 330 edits |

**Stale rollback files alone = 67G** reclaimable with three `rm`s (each is
5–8 days old, post-verified compaction; tonight's cms backup already failed
ENOSPC, so the headroom is needed now — see Risk).

**CMS content vs file: 41MB live content in a 22G file (~0.2%).** The rest
is revision bodies (137,272 revisions on 10k docs), meta-index entries
(114,846), embeddings, and bbolt freelist/dead pages. The file regrew
2.4G → 22G (~3.3G/day) in the 6 days since the 2026-11-13 export/import
compaction — this is write-churn allocation, not content growth.

## Reconciliation of completed work

- **Lesson/report migration: DONE.** Wiki `Education:` namespace = 177
  pages (hub + due/index + ~124 lesson topics incl. series), `Reports:` =
  17 pages, `PrivateNews:` = 1. MediaWiki 1.46.2 at
  `https://wiki.h3.gizmo-thailand.com`, API at `/api.php` (note:
  `WIKI_HOST=.../v0` in `wiki-h3-gizmo.env` is stale vs
  `ssot.mediawiki-news.yml`'s canonical root API — board-api honors
  `WIKI_API_URL` or falls back to `{host}/api.php`; worth verifying which
  the running service resolves).
- **Wiki-primary lesson writes: ON** (`WIKI_EDUCATION_WRITE=wiki`,
  cutover 2026-11-07; `/wp/lesson/*` permalinks 301 → wiki via idc02 edge
  fragment). WP `lesson` CPT is a frozen archive: 137 private posts,
  ~7.6MB content — deleting it later is cosmetic (0.007% of the problem).
- **mddb-cms compaction: DONE then regrew.** 2026-11-13 export/import took
  the file 24G → 2.4G (<4G verified). Six days later the file is 22G on
  the same ~41MB of content — the compaction proved the db is overhead,
  and the regrowth proves the writers haven't changed.
- **mddb-cms nightly backup: FAILED last night** (2026-11-19 03:37,
  `no space left on device` writing the filecopy; `mddb-backup.service`
  in failed state; `filecopy-mddb-cms-20261119-0255.db.UNVERIFIED` = 0
  bytes). Last good cms gz: `mddb-cms-20261118-0308.db.gz` (3.3G). Backup
  retention is ~2 sets — thin, and now the copy step can't even write.

## Measured inventories

### mddb-cms (:11027) — 19 collections, 10,002 docs, 137,272 revisions

| collection | docs | revisions | meta-idx | export bytes | nature |
|---|---|---|---|---|---|
| infrastructure-ssot | 7,426 | 12,291 | 45,774 | 32MB | derived mirror of repo SSOT (sync-ssot-to-mddb.py) — rebuildable, not movable |
| ada-cms-pages | 1,408 | **103,656** | 53,911 | 5.0MB | reports 920 / pages 455 / archive 32; ~248 docs touched/day; hot keys are cam-wall, digests, indexes |
| ada-cms-pages-kk | 159 | 13,264 | 3,916 | 323K | kk-lane mirror |
| chaba-lessons | 176 | 947 | 3,011 | 2.0MB | already mirrored to Wiki (dual-write) |
| documents | 275 | 275 | 3,434 | 285K | uploaded docs |
| kb-operations / kb-features / kb-system / kb-development | 402 | 402 | ~2.9K | ~1.5MB | authored KB |
| ada-cms-automation | 75 | 6,356 | 1,006 | 74K | regen REGISTRY configs — operational, not content |
| remainder (ada-cms-pages-mn/-kk-dev, chaba-*, devin-kb, ssot, ada-ha-events-tony) | ~81 | ~280 | — | ~90K | small |

All collections: `collection-config` = `{type: default}` — **no
`maxRevisions` set anywhere on the cms plane.** ~17k revisions/day land on
ada-cms-pages alone (hourly `chaba-cms-regen` REGISTRY sweep + 10–15min
cam-wall + 15–30min digest writers each mint a revision per page).

### WP boards (Plesk; REST-measured, `status=any` totals)

| type | count | content est. | class |
|---|---|---|---|
| news | 3,962 | ~13.3MB | **feed** (hourly ingest + digest clustering) — not movable |
| lesson | 137 (private) | ~7.6MB | frozen archive, already in wiki |
| media | 167 | ~12MB (100-item sample sum) | attachments |
| pages | 14 | ~1.5MB | authored |
| cam | 83 | <0.1MB | ops ledger |
| ops_error / score / nest_job / repeat_ask / activity / trip / place / timeline_block / asset / contact / reminder / bench / render_job / report / ops-event | ~150 | <1MB | operational records |
| posts / comments / users | 9 / 149 / 3 | — | standard |

WP total movable-by-wiki content: **≤ ~10MB** (pages + any authored posts;
lessons are already in wiki). News is a feed; ledgers are records.

### Wiki (MediaWiki, same Plesk host as WP origin)

253 pages / 330 edits / 3 users; Education 177, Reports 17, PrivateNews 1,
Infrastructure + main namespaces small. Estimated content: single-digit MB.
Wiki growth headroom is effectively unlimited vs. what we could move —
nothing we own would move the needle in either direction.

### mddb-ops (:11026) — adjacent finding, out of CMS scope but the biggest live file

host-logs 423,634 docs / 548,820 revs / 2.1M meta-idx; device-telemetry
9,699; ada-nest-heartbeats. **The daily retention sweep is still broken:**
today's `prune-old-docs.service` logged `host-logs: list failed — timed
out` on :11026 (the collection is past the API-enumerable size again —
same MEM-0871 failure mode the 11-11 compaction was supposed to relieve;
3d policy = ~114k docs, currently 423k). The ops db regrew 0 → 29G in 8
days post-compaction.

## Writers / readers / automation map

**mddb-cms writers:** `chaba-cms-regen` (hourly, REGISTRY-driven page
rebuilds), `cam-wall-cms-vps` (~10–15min, wall-*/cam-* pages — markdown
with image URLs, no embedded bytes), `chaba-review-digest` /
`ops-health-report` / `fleet-jobs-report` / `yomi-mddb-digest` /
`wp-news-digest` (15–30min report pages), `mddb-memory-standard`,
`embed-lane-lessons`, `chaba-lessons-due/audit`, board-api `/publish` +
`/report` + `/lesson` (unified mutation door), `sync-ssot-to-mddb.py`
(infrastructure-ssot), plus manual `report-note.py` flows.

**mddb-cms readers:** `chaba-cms-render` (:8010, → cms.surf-thailand.com
via idc02 edge), board-api `/report` (search|note|create), Ada MCP search
tools, kanban/index consumers, agent `/v1/search` on infrastructure-ssot
(the `chaba-ask` path), vector search on the embed plane.

**WP writers:** board-api `wp_api` seam (news ingest, nest_job, frozen
lesson), Plesk scheduled-task workers (usage pull-render), LINE-managed
lane tools. **Readers:** public members via
boards.surf-thailand.com (CF edge) → origin boards.h3.gizmo-thailand.com.

**Wiki writers:** board-api `MediaWikiSink` (`/publish`, News pages),
`/lesson` door (wiki-primary), `lessons-due` (Education:Due/Index),
bot user `ada`. **Readers:** public web; Education/PrivateNews gated by
Lockdown (inhouse-after-sso decision, OPS-1046).

**Access boundaries:** WP app-password creds only on service hosts
(`~/.config/secrets/wp-boards.env`); wiki bot creds in
`wiki-h3-gizmo.env`; MDDB banks are tailnet-only; cms.surf-thailand.com
public render sits behind CF Access. Migration to wiki would change the
visibility boundary of anything moved: wiki Education/PrivateNews are
already Lockdown-gated, but MDDB meta-taxonomy search
(domain/kind/fresh_for) has no wiki equivalent — retrieval would degrade
to wikitext search unless templates/categories replicate it.

## Scenario comparison

| | A — no move + retention/compaction | B — move selected document-like content | C — broader migration |
|---|---|---|---|
| Scope | Delete 3 stale rollback files; set `maxRevisions` + `/v1/truncate` on cms+ops collections; repair host-logs retention; recompact cms/ops; fix backup headroom | Move authored reports/KB (~5–10MB: ada-cms-pages `kind=report` authored subset, kb-*, documents) to Wiki; keep feeds/ledgers/mirrors | Move all of ada-cms-pages + movable WP CPTs to Wiki |
| Reclaimed bytes | **~90–110G** on idc03 (67G stale files + ~20G cms regrowth + ~20G ops regrowth, recurring) | **~0** — content is ~10MB; the mddb file doesn't shrink on delete (needs a compaction anyway, which A already does) | **~0** — same reason; ~50MB total |
| Wiki growth | none | +~10MB | +~50MB + ongoing revision churn from living docs |
| Consumer impact | none (housekeeping) | cms-render, board-api `/report`, Ada search tools, dashboards need read-path retarget; URL redirects; MDDB meta-taxonomy lost | breaks cam-wall/digest/regen writers' page model (they'd spam MediaWiki revisions), meta-search lost, news feed can't move anyway |
| Ops burden | adds retention guarantees that are currently missing | dual-surface confusion: which report lives where | sustained — wiki becomes a second churn target |
| Backup/restore | restores backup headroom (tonight's backup failed ENOSPC) | unchanged | unchanged (Plesk backups unaffected) |
| Access control | unchanged | wiki Lockdown already gates Education/PrivateNews — parity achievable | same, but more content classes to map |
| Rollback | trivial (files are already-verified stale; config changes revert) | export back to MDDB — moderate | hard — URL/consumer surgery both directions |

## Why migration can't fix this

1. **Content isn't the bytes.** All movable content ≈ 41MB (mddb-cms) +
   ~10MB (WP) vs 93% disk usage driven by file-level churn.
2. **bbolt never shrinks.** Deleting docs feeds the freelist; only
   export/import reclaims physical space. A migration would *still*
   require a compaction to realize any bytes — and the compaction alone
   recovers ~99.8% of what's recoverable.
3. **The churn is structural.** ~17k revisions/day on ada-cms-pages with
   no `maxRevisions`; ops host-logs unbounded because enumeration times
   out; stale 67G of rollback files kept past their verification window.
4. **What's movable was already moved.** Lessons (the actual knowledge
   corpus) are wiki-primary; the mddb mirror is the agent-retrieval
   surface by design.

## Recommendation — Scenario A, phased

**Phase 0 — tonight (needs Tony approval; file deletes):**
- `rm` the three verified-stale rollback files: cms `mddb.db.pre-compact`
  (24G, 2026-11-13), ops `mddb.db.precompact-20261111` (31G), leader
  `mddb.db.pre-compact-20261113` (12G) → **+67G free**, restoring backup
  headroom before tonight's 02:30 run. Delete the 0-byte `.UNVERIFIED`
  filecopy.

**Phase 1 — revision bounds (cms plane, config-only, reversible):**
- Set `maxRevisions` (suggest 10) + `/v1/truncate` on ada-cms-pages,
  ada-cms-pages-kk, ada-cms-automation, infrastructure-ssot; leave
  chaba-lessons at a higher bound or exempt (authored). Expected: stops
  the 17k-rev/day bleed that regrew 20G in a week.

**Phase 2 — ops retention repair:**
- host-logs is past enumerable size again: rerun the
  backup→scratch-enumerate→delete-batch path (precedented twice) or
  `/v1/truncate` + tighter shipper-side filtering; then verify
  `prune-old-docs.service` completes `host-logs` on :11026 within timeout
  (target <~114k docs under the 3d policy).

**Phase 3 — compaction cadence:**
- Schedule export/import compaction (proven runbook
  `docs/ssot/jobs/cms/2026-11-13-mddb-cms-compact-export-import.yml`)
  size-triggered (e.g., file >3× exported content) or monthly for cms,
  weekly-ish for ops until Phase 2 lands. Alternatively pursue mddb-side
  freelist reclaim as a feature (bigger lift).

**Phase 4 (optional, non-storage, only if Tony wants it) — surface
consolidation pilot:**
- Pick ~10 authored ada-cms-pages `kind=report` docs (not
  machine-regenerated), mirror to `Reports:` like the lesson pattern,
  keep MDDB copies. Measures UX/retrieval cost honestly; expected storage
  delta ≈ 0 — do it for consolidation value, not disk.

## Risks / watch items

- Backup window: cms filecopy backups fail ENOSPC **today**; Phase 0
  unblocks them. gz backups retain ~2 sets — consider 3+ once headroom
  returns.
- `WIKI_HOST` env says `/v0` but canonical API is root `/api.php` —
  verify board-api's resolved endpoint (it worked for the migration, so
  `WIKI_API_URL` is probably set correctly; flag for hygiene).
- Wiki is on the same Plesk shared host as the WP origin — moving content
  there shifts bytes to a metered shared-host disk we can't measure from
  here; another reason C is unattractive at scale.
- `~/var/cache/devnest` = 33G on the same filesystem — worth a separate
  retention look; out of this card's scope.

## Reproduce the measurements

```
# idc03 disk + banks
ssh idc03 'df -h /; du -sh ~/.config/containers/mddb*/data ~/mddb-backups ~/var/cache'
curl -s http://100.102.134.91:11027/v1/stats   # cms: docs/revs/meta-idx, db size
curl -s http://100.102.134.91:11026/v1/stats   # ops: host-logs etc.
curl -s http://100.102.134.91:11023/v1/stats   # leader

# content bytes (export per collection, sum)
curl -X POST http://100.102.134.91:11027/v1/export -d '{"collection":"ada-cms-pages"}'

# WP totals (on idc03, creds in ~/.config/secrets/wp-boards.env)
GET {WP_SITE_URL}/index.php?rest_route=/wp/v2/<type>&per_page=1&status=any  # X-WP-Total

# Wiki
curl 'https://wiki.h3.gizmo-thailand.com/api.php?action=query&meta=siteinfo&siprop=statistics&format=json'
```
