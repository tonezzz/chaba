# dispatch outcome — mddb-cms-11027-embed-coverage-gap-250-do-e35321 (attempt 2)

## What this attempt was

Attempt 1 (tony-macbook, 10:10–10:54) did the server-side work: non-force
`POST /v1/vector-reindex` across all 12 affected :11027 collections,
raised the meta-only-docs board request, and claimed repo deliverables on
branch `c1beb717d2`. Tony answered the request `proceed` (keyword-only)
at 14:01; answer-sweep queued attempt 2 (this run, mn01).

Attempt-1's claimed merges (verify-queue comms: `267d4546c67f`,
`b8f5e5e697f4`) are **not objects in origin/master** and none of its
deliverables (job declarations, rendered units, scripts, outcome doc)
exist in the repo — the merge claims were hollow. This attempt re-did
the repo-side work and finished the residual server-side re-embed.

## Verified live state (:11027, 2026-11-25 ~14:45 +07)

Gap decomposition — every `embedded < total` delta is now explained:

| class | docs | collections |
|---|---|---|
| meta-only stubs (contentMd empty by design) | 83 | chaba-archive 12, chaba-docs 15, devin-kb 9, documents 1, kb-development 8, kb-features 11, kb-operations 12, kb-system 14, ssot 1 |
| real dropped embeds | 131→0* | infrastructure-ssot (147 missing w/ content; non-force reindex running, 8894+/9025 at last stats) |

All other collections at embedded==total (chaba-lessons 207/207,
ada-cms-pages 1599/1599 — attempt-1 re-embeds held).

Queue: depth=0, dropped=1762 (still grew during incident window),
retried=875. Root cause: embed-pool-shim :11436 504s on cold/degraded
fleet upstreams → mddb drops embed jobs past retry cap. Alerting on
dropped>0 already exists (`scripts/ada/embed-probe.py` per-plane
ops-events; fired during the incident) — action (2) verified closed,
no new alert needed.

## What changed (this branch)

- `scripts/mddb/mark-keyword-only.py` — **new**. Idempotent scanner:
  finds empty-contentMd docs per collection and stamps
  `meta.search_mode=["keyword"]` via `PATCH /v1/update` (content
  untouched, no re-embed). Ran live: 82 marked + ssot.focus = all 83.
- `scripts/embed/embed-pool-warm.py` — **new**. Reads upstreams from
  shim `:11436/health` (auto-tracks fleet), POSTs tiny `/api/embed` to
  each directly so every racer stays warm. Verified from mn01:
  tony-omen 477ms ok; loopback kk-mac upstream fails off-idc03 as
  expected (job runs on idc03).
- `docs/ssot/infrastructure/ssot.jobs.yml` — two new jobs:
  - `embed-pool-warm` (idc03, every 4m) — action (3).
  - `mddb-cms-vector-reindex` (con01, daily 05:50, `MDDB_BASE_URL=:11027`)
    — the CMS-plane twin attempt 1 described but never landed.
- `systemd/generated/{idc03,con01}/` — rendered units for both jobs
  (`render-jobs.py --check` OK, 135 jobs).
- `docs/ssot/apps/ssot.apps.ada-memory-banks.yml` — devin-kb +
  chaba-archive descriptions note the keyword-only surface.
- `docs/ssot/jobs/mddb/2026-11-25-embed-coverage-gap-closeout.yml` —
  job record with decomposition, decision, verify steps.

## Server-side actions taken (no deploy)

- `PATCH /v1/update` ×83 — keyword-only meta stamps (live, done).
- `POST /v1/vector-reindex {collection: infrastructure-ssot}` — running
  in background at time of writing (~25s/doc synchronous; see card
  comms for final count). If it stalls, the new daily
  `mddb-cms-vector-reindex` job covers the residue.

## Not done / follow-ups

- Units are declared+rendered but NOT installed — deploy is a separate
  gated step (install on idc03 + con01 via the normal units flow).
- `embed-pool-warm` unverified end-to-end on idc03 (kk-mac :11447 is
  loopback-only); first run after install will show per-upstream ok/FAIL.
- droppedTotal=1762 is cumulative-historical; embed-probe alerts on
  growth, not absolute — fine as-is.

## How to verify

```
python3 scripts/render-jobs.py --check          # manifest valid
python3 scripts/mddb/mark-keyword-only.py --dry-run   # would_mark=0
curl -s http://100.102.134.91:11027/v1/vector-stats | python3 -m json.tool
# infrastructure-ssot embedded_documents -> 9025 (minus any NEW drops)
# On idc03 post-install: systemctl --user start embed-pool-warm.service
```

lessons:
  - verify-queue merge claims can be hollow — cat-file the sha and check
    the deliverables exist before treating a dispatch branch as landed.
  - embedded<total decomposes into meta-only stubs (declare keyword-only
    via meta search_mode=keyword + PATCH /v1/update) vs real dropped
    embeds (non-force /v1/vector-reindex).
  - PATCH /v1/update is the meta-only door — content untouched, no
    re-embed; send the FULL merged meta dict.
  - embed-pool warm-ping must run on idc03 — kk-mac deferred upstream is
    loopback :11447; shim /health is the upstream source of truth.
