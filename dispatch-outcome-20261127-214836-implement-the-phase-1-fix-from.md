# Dispatch outcome — vector-reindex async jobs + bounded sweep (OPS-1515 phase 1)

## What changed

`scripts/mddb/vector-reindex.py` rewritten to drive **async reindex jobs**
(`POST /v1/vector-reindex {collection, async:true}` → 202 `{jobId}`, then poll
`GET /v1/vector-reindex/jobs/{id}`) per the phase-1 recommendation in
`docs/ssot/jobs/mddb/2026-11-27-vector-reindex-batch-triage.yml` (found on the
sibling triage dispatch branch — it was not yet merged into this worktree's
base). Client-only; deployed mddb 2.18.10 already supports the API.

All 7 card requirements implemented:

1. Async POST + poll per collection (no more 64 sequential sync calls).
2. Global sweep deadline: `MDDB_REINDEX_SWEEP_BUDGET` (default 2400s, inside
   the 45-min unit budget) + `MDDB_REINDEX_LAUNCH_MARGIN` (default 300s) —
   no new jobs launch in the last ~5 min; in-flight jobs continue
   server-side (no cancel endpoint exists).
3. Collections sorted by `/v1/stats` `documentCount` ASC — the 153,490-doc
   `ada-ha-bank-devin-handoff` runs last.
4. Per-job poll deadline `MDDB_REINDEX_JOB_TIMEOUT` (default 900s, falls back
   to legacy `MDDB_REINDEX_TIMEOUT` which the con01 unit sets to 1800),
   capped by the sweep deadline — expiry marks `deferred` and continues.
5. Per-collection `vector_reindex_failed` ops-event emitted immediately on
   `failed>0` or non-empty `errors[]`, including a 3-entry errors[] sample
   (previously discarded).
6. Final `vector_reindex` summary lists per-collection results plus
   unattempted/deferred collections explicitly; exit 1 only on real
   failures.
7. On start, `GET /v1/vector-reindex/jobs` attaches to/polls already-active
   jobs; a 409 on launch re-lists and attaches to the winner. `lost` (404 —
   leader restart forgets in-memory jobs) recorded as error.

`MDDB_REINDEX_MAX_CONCURRENT` deliberately unused (GO-054 needs mddb
≥2.19.8; deployed is 2.18.10 → client keeps its own serialization).

Trail doc: `docs/ssot/jobs/mddb/2026-11-27-vector-reindex-async-client.yml`.
Commit `bf2e7a6a594` on `dispatch/20261127-214836-implement-the-phase-1-fix-from`.

## Verification

- Mocked-HTTP tests (throwaway, since removed): ASC ordering, active-job
  attach without POST, 409→attach-to-rival, poll-deadline deferral,
  launch-cutoff unattempted, immediate failure event with errors[] sample,
  exit codes — all passed.
- **Live run** from this worktree on idc02 against leader :11023 with a
  bounded budget (SWEEP_BUDGET=90 LAUNCH_MARGIN=30 JOB_TIMEOUT=30 POLL=3):
  38/64 collections attempted in the launch window; 26 unattempted
  including `ada-ha-bank-devin-handoff` (153,490 docs — grew from 149,550
  at triage). Ops events confirmed in `ada-ha-events-tony` via mddb-ops
  :11025: two `vector_reindex_failed` events and the PARTIAL summary
  (`ops-vector-reindex-vector_reindex-20261127221002-2692`).
- Real finding surfaced by the new errors[] path: 4 embed failures
  (`ollama API error 504: no upstream answered in time`) on
  `ada-ha-snapshots-ada` and `ada-cms-pages` — provider-side flakiness the
  old script discarded.
- Remaining verification: next con01 05:40 timer run (the unit runs the
  served checkout's copy — this branch must merge + repo-sync first).

## Notes for reviewer

- `MDDB_REINDEX_TIMEOUT` is honored as a fallback for the new
  `MDDB_REINDEX_JOB_TIMEOUT` so the con01 unit's existing `=1800` env keeps
  meaning "max wait per collection" (now the poll deadline, still capped by
  the sweep deadline). Default when unset is 900s per the card.
- A job still running at its deadline is `deferred`, not failed — exit 0 on
  deferral-only runs; the summary event carries the explicit gap list.
- The 149k→153k-doc giant will likely defer nightly until phase 2/3
  (server-side batching/sharding or cadence change) — expected, and next
  run attaches if it's still active.

lessons:
  - mddb /v1/search filterMeta returns arbitrary subsets under limit — verify ops-event docs by exact key or filter client-side
  - ops-event keys need a ms suffix once multiple same-type events can land in one second (per-collection failure events)
  - the OPS-1515 triage doc lived only on the unmerged sibling dispatch branch — fetch origin/dispatch/* before assuming a referenced jobs doc is missing
