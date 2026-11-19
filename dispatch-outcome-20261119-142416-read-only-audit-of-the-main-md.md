# Dispatch outcome — mddb-main-bank-revision-churn-audit (2026-11-19)

Read-only audit of the four post-compaction main-bank collections on the
idc03 MDDB leader (:11023, db 2.75 GiB, 28,211 docs / 188,609 revs live).
No writes, no config changes, no service touches, no embed probes.
Per-doc revision census of all 10,979 docs was taken via `POST
/v1/revisions` + `/v1/search`; totals reconcile exactly with `/v1/stats`.

## Deliverables

- `docs/reports/mddb-main-bank-revision-churn-audit-2026-11-19.md` —
  evidence-backed report (counts, maxRevisions, heavy keys, cadence,
  producer traces, expected-vs-heartbeat split, recommendations).
- `docs/reports/mddb-main-bank-revision-churn-audit-2026-11-19/*-census.json`
  — full per-doc census for the four collections.

## Key findings

- **maxRevisions live:** only `ada-ha-bank-devin-tony`=20 of the four in
  scope; home/general/devin-handoff are `configured:false` — as are ~28
  other main-bank collections (projects-tony 19,028 revs/162 docs,
  device-telemetry 20,265/3,567, etc.). The 10-26 "main x6 colls=20"
  policy is not live.
- **Root cause A (biggest, active now):** `Mddb.list_docs`
  (`sync-ada-memory-to-mddb.py:178`) requests `limit:5000` but the server
  caps pages at 1,000 → `sync-devin-summaries` (tony-omen `*:45`) re-adds
  ~1,321 invisible `devin/*` docs EVERY HOUR (~31.7k writes+embeds/day) —
  1,321 of 1,323 docs revised <24h sit outside the first-1,000 window.
- **Root cause B:** ada-voice `memory_ops.record_use_bg` writes one
  revision per recall hit (`use_count`/`last_used` bump, fire-and-forget)
  — `use_count` changes in ~94-99% of consecutive revs on every hot doc;
  the five `note/flood-*` docs in home hold 17,984/21,696 revs (bursts of
  300-500/day, median 44 s, during the Oct flood window).
- **Root cause C:** `ada-memory-sync` ping-pong — use-tracking fields are
  in `MANAGED_FIELDS`, so every touched doc looks dirty vs the vault and
  is rewritten hourly (192/195 drop-writes land at minute `:00`), plus
  `build_meta` stamps `valid_from`/`last_verified` with `today` → forced
  daily 00:00 rewrite. Live cadence is still `:00` despite the repo's
  11-18 move to `:17` (installed unit not re-deployed).
- **Expected history:** handoff's dispatch-close-out (6,188 docs, ~1.12
  rev/doc) and devin-session summaries — healthy; ~85-90% of in-scope
  revisions are duplicate/heartbeat writes.

## Recommended actions (in report)

1. Paginate `list_docs` (offset until short page) — kills the hourly
   mass re-add + embed storm.
2. Debounce `record_use_bg` (≤1 write/doc/day, or PATCH /v1/update if it
   stores no revision — unverified, noted).
3. Exclude `use_count`/`last_used`/`outcome*` from the sync dirty-check.
4. Stop stamping `today` into `valid_from`/`last_verified` defaults.
5. Set maxRevisions: handoff/home/general = 10, keep devin-tony = 20;
   extend to the other unbounded churners; then truncate + offline bbolt
   compact per `docs/kb/mddb-prune-compact.md`.

## Verify

`python3 /tmp/mddb-audit/census.py <collection>` (script in this run's tmp;
per-doc totals reconcile with `/v1/stats`), or
`curl -s http://idc03:11023/v1/collection-config?collection=ada-ha-bank-home`
(configured:false confirmed) and `POST /v1/search {collection:
ada-ha-bank-devin-tony, limit:5000}` → returns exactly 1,000 docs.

lessons:
- /v1/search caps page size at 1,000 regardless of `limit` — any
  list_docs-style call assuming a bigger page silently sees a truncated
  collection and will re-add "missing" docs every run.
- MDDB revisions store timestamp+meta only (no contentMd) — every
  fire-and-forget meta bump (use_count/last_used) costs a full revision
  row; debounce touch-writers or they dominate collection churn.
- `GET /v1/collection-config?collection=X` is the cheap way to check
  maxRevisions; `POST /v1/revisions {collection,key,lang}` gives
  per-doc rev history (GET returns 'method not allowed').
- Live timer cadence can lag repo unit files — verify write-minute
  histograms in revision timestamps before attributing a producer.
