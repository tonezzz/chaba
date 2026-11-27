# Dispatch outcome — bound the reindex batches and isolate per-collection failures

Card: `mddb-vector-reindex-timeout-embed-failures` (OPS-1515, OPS-1511 follow-up)
Date: 2026-11-27 — triage-only; no fix applied.

## What was found

The con01 daily sweep (`scripts/mddb/vector-reindex.py`, 05:40, 45-min
`TimeoutStartSec`) fires 64 **sequential synchronous**
`POST /v1/vector-reindex` calls — one per collection — each with a 30-min
HTTP timeout and **no sweep-level deadline**. Live `/v1/stats` on the idc03
leader (mddb 2.18.10): 64 collections / 173,924 docs, and
`ada-ha-bank-devin-handoff` alone holds **149,550 docs (86%)**.

Server side (verified against upstream `tradik/mddb` source): the handler
materializes every doc of the collection up front, then per doc does a
`VectorStore.Get` — **one bolt View transaction per document** — plus
hash/chunk/embed (30 s cap per chunk)/store/index. The 149k-doc collection
is ~149k bolt txs inside a single request; on 2026-11-27 idc03 was under
OPS-1511 memory pressure (swap full, mddb swapped), which is the plausible
reason the run blew the 45-min budget where 11-26 finished.

Isolation gaps: the endpoint returns per-doc `errors[]` but the client
script discards it (the 13 failures have no doc IDs/reasons and will
re-fail daily); the summary ops-event is emitted only after the last
collection, so the SIGTERM'd run left zero telemetry; no resume state —
each run restarts at collection #1.

## Key discovery — fix is cheaper than expected

Deployed **2.18.10 already supports async reindex jobs** (#347, shipped
2.18.4): `{"async":true}` → `202` + jobId, poll
`GET /v1/vector-reindex/jobs/{id}` for done/percent/ETA and a final result
including `errors[]`; `GET /v1/vector-reindex/jobs` lists jobs; a second
reindex of the same collection returns `409`. Verified live with a 1-doc
collection (`reindex_546dd26e68a31479`, completed skipped=1).

Not present on 2.18.10: GO-054 reindex concurrency slots / `queued` status
(2.19.8+), and **no limit/offset/batch params exist even on upstream
2.19.13** — per-collection granularity is the API floor. Jobs are
in-memory only (leader restart forgets them; 404 says so).

## Recommendation (in job record)

Phase 1 — client-only rewrite of `vector-reindex.py`: async jobs +
global deadline inside the unit budget + collections sorted by doc count
ascending (giant last) + per-job poll deadline with "deferred" marking +
per-collection failure ops-events carrying `errors[]` samples + attach to
already-running jobs on startup. Phase 2 — when mddb ≥2.19.8, set
`MDDB_REINDEX_MAX_CONCURRENT=1` and let the server serialize. Phase 3 —
upstream/fork work for real batching (bulk `GetVectors`, pagination,
persistent jobs) and/or shard `ada-ha-bank-devin-handoff` off the daily
cadence.

Full analysis: `docs/ssot/jobs/mddb/2026-11-27-vector-reindex-batch-triage.yml`

## Follow-up card

Filed `vector-reindex-async-jobs-bounded-sweep` via board-api for the
phase-1 implementation.

## How to verify

- `curl http://100.102.134.91:11023/v1/stats` — 64 collections,
  ada-ha-bank-devin-handoff = 149,550 docs.
- `curl -X POST .../v1/vector-reindex -d '{"collection":"ssot","async":true}'`
  → 202 + jobId; poll `/v1/vector-reindex/jobs/{id}` → completed.
- Job record cites all evidence; upstream refs: `vector_reindex.go`,
  `vector_reindex_jobs.go`, `reindex_slots.go` @ tradik/mddb main.

lessons:
- mddb vector-reindex cost scales with collection doc count (per-doc bolt tx for hash-skip), not embed count — one 149k-doc collection is 86% of the sweep.
- async reindex jobs (#347) are already live on deployed mddb 2.18.10 — poll `/v1/vector-reindex/jobs/{id}`; jobs are in-memory, forgotten on restart.
- GO-054 `MDDB_REINDEX_MAX_CONCURRENT` needs mddb ≥2.19.8 — no-op on 2.18.10.
- vector-reindex.py drops the endpoint's `errors[]` — per-doc failure detail exists but never reaches ops events.
- A sync sweep with per-call timeouts but no global deadline cannot fit inside a systemd unit budget — bound the sweep, not the calls.
