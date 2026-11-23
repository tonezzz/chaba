# dispatch-outcome — embed-lane-banks-search-pagination (2026-11-23, tony-macbook)

## What changed
- `tests/embed/test_embed_lane.py` — added `TestDocsPagination` (5 tests)
  covering the `_docs` offset-pagination contract: multi-page walk until
  short page, short-first-page single request, exact-page-boundary stop,
  offset-ignored server no-spin guard, dict-wrapped `{"results": []}`
  shape. 12/12 tests pass.
- `docs/ssot/jobs/mddb/2026-11-23-embed-lane-banks-search-pagination-verify.yml`
  — trail doc.
- Commit `0474075937` on `dispatch/20261123-144230-scripts-embed-embed-lane-py-do`
  (not pushed — dispatch rules).

## State found
The actual `_docs` pagination fix (`d317c76fec`) and the big backfill
(3115+198 docs) were already on master from the 11-17 dispatch —
salvage-merged after that unit exited 1 at close-out (idc02 lacked push
creds). Two 11-20 retries died ~2min in on provider rate limits before
working. What remained was the unit test + a fresh live verify/delta
backfill.

## Result
- `python3 -m unittest tests.embed.test_embed_lane` — 12/12 OK.
- `python3 scripts/embed/embed-lane.py banks` — 370 new
  `ada-ha-bank-devin-handoff` docs delivered (live-written collection,
  11254→11624 keys), 0 failed; all other 23 collections todo=0.
- Verification: key-set diff source → mddb-embed :11028 over
  contentMd-bearing docs = **0 missing on all 24 BANK_COLLS** (both
  sides fetched with the paginated `_docs`). Queue: depth=0,
  `dropped` delta = 0 during the run.
- Caveat on `dropped`: the cumulative counter reads 2 (both drops
  predate this run, accumulated inside an earlier upstream-504 window
  since the ~11-18 idc02 service start). A cumulative counter can't
  return to 0 without restart — delta=0 is the honest reading.
- 267 source docs have no contentMd (uncopyable by design; was 142 on
  11-17 — growing surface). devin-kb is 9/9 content-free, have=0 is
  correct.

## How to verify
```
python3 -m unittest tests.embed.test_embed_lane
python3 scripts/embed/embed-lane.py banks --dry-run   # todo=0 everywhere
curl -s -X POST http://100.123.163.11:11028/v1/vector-stats -d '{}' \
  | python3 -m json.tool                              # queue block
```

lessons:
- Prior dispatch's work can be salvage-merged while its unit still
  reports "failed" — always check master (git log) and the card's trail
  file before redoing the spec.
- /v1/vector-stats is a cached snapshot (statsAgeSeconds) — during
  async drain, embedded_documents lags the /v1/search key set; use
  search keys for coverage, stats only for queue health.
- mddb-embed queue `dropped` is cumulative since service start, not
  per-run — compare before/after, don't expect 0.
- `embed-lane.py stats` (and lessons/news/recall) require LITELLM creds
  even though stats never uses them; banks is the only cred-free
  subcommand — call /v1/vector-stats directly instead.
- Key-set audits must filter contentMd-bearing docs: ~270 source docs
  (incl. all of devin-kb) have no contentMd and will always diff as
  "missing" — uncopyable by design.
