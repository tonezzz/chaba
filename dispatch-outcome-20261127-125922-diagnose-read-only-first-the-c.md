# Dispatch outcome — mddb-ops-write-latency-triage (2026-11-27)

## What was found

Read-only diagnosis of the mddb-ops write-latency congestion breaking fleet
log shipping. **Root cause identified: a detached drain loop on idc03
(PID 3862968, started 10:48 ICT by the ada-review-refresh-prune-timeout-fix
dispatch) runs `prune-old-docs.py --only host-logs --budget-seconds 1800` in
an infinite `while true` + 90s-sleep loop.**

- host-logs has 592,247 docs, **387,737 expired** (>3d) — backlog from weeks
  of broken retention sweep.
- Every loop iteration's `POST /v1/documents:deleteWhere` (limit=1000,
  110s client timeout) **times out client-side every time**
  (`/tmp/prune-drain.log`: "deleteWhere failed — timed out (deleted 0
  before failure)" ×20+), but the server-side handlers keep running
  **4,000–4,900s (66–82 min)** each — orphaned from dead clients.
- bbolt allows one write tx: dozens of overlapping orphaned deleteWhere
  handlers convoy the write lock while walking the 2.97M-entry meta-index
  and committing deletes with `MDDB_FREELIST_SYNC=true` on a **26.85GB db
  with ~23.6GB freelist**. `/v1/add` and `/v1/ingest` queue behind →
  125–198s handler times vs the 120s write timeout.
- Self-reinforcing: timeout ≪ handler time → every retry/iteration spawns
  more orphans on the same cursor range → net drain ~2 docs/min (~134 days
  projected; the loop can never succeed).

## Live probe results (2026-11-27 ~13:30 ICT, read-only + 12 tiny probe writes)

- `/v1/add` n=12: 10.0–27.0s → **p50≈14s, p95≈26s** (28h server histogram
  p50 was 0.5s; healthy under-load baseline ~2–6s).
- `/v1/ingest` 5 docs (shipper shape): 12.8s.
- `/v1/search` host-logs limit=5: 58.6s; `/v1/get`: 10ms — point reads
  unaffected → write-lock convoy, not general overload.
- `deleteWhere` dryRun: 2.2s → 17.5s as congestion returned.
- Congestion correlates with the deleteWhere drain activity started
  ~10:18–10:48 ICT today — NOT a specific collection's read load; the
  write path is globally serialized.

## Ruled out

Replication (standalone, lsn=0, no followers), embeddings (disabled on
ops), leader :11023/mddb-cms (separate DBs), host CPU alone (load ~12 but
reads stay fast).

## Aggravators

idc03 memory ~1GB avail/15GB (3× mddbd + litellm + HA), mddb-ops
GOMEMLIMIT=2GB at RSS ~1.95GB, stats recompute 127–226s every ~5min never
catching up (statsAge 2.3h), db file grew 26.37→26.85GB during observation.

## Actions taken (all read-only / board writes)

- Posted full diagnosis as card comment on `mddb-ops-write-latency-triage`.
- Raised board request `approval-needed-mddb-ops-write-congestio-f92e57`:
  recommended **(A)** kill drain loop PID 3862968 now (client-side only,
  no MDDB service/data change; orphans self-drain ~1–2h; /add back to
  ~2–6s) **+ (B)** schedule Procedure-C offline bbolt compact
  (docs/kb/mddb-prune-compact.md, verified 76G→6.2G on 2026-11-24;
  26.85GB→~3GB, ~15–30min downtime, `.pre-compact` rollback) to kill the
  freelist poison; retention backlog then drains cheaply. Alternatives
  offered: A-only, or Procedure-B export→fresh re-add of non-expired docs.
- Trail written: `docs/ssot/jobs/mddb/2026-11-27-write-latency-triage.yml`.
- Probe collection `devin-latency-probe` deleted afterwards
  (delete-collection 200 in 62s — itself queued behind the convoy).
- **No change applied to production MDDB service or data** — per card,
  awaiting the approval request.

## How to verify

- `journalctl --user -u mddb-ops.service` on idc03: deleteWhere/
  add/ingest timeout-WARN rate should collapse after the loop is killed
  and orphans drain (~1–2h).
- `ps -p 3862968` on idc03: gone after kill.
- `/metrics` on :11026: `mddb_http_request_duration_seconds` for
  `/v1/add`, `/v1/ingest` p50/p95 trend down; deleteWhere count stops
  growing.
- `/tmp/prune-drain.log` on idc03 stops appending.
- After compact: `/v1/stats` databaseSize ~3GB, statsAge drops to seconds,
  freelist pressure gone.

## Follow-ups flagged (not carded — board request covers the fix)

- deleteWhere/delete-batch can outlive any client timeout on a big db —
  mddb should chunk commits per-doc or offer detach+poll; consider a
  server-side limit guard.
- prune-old-docs.py logs no per-call progress — "deleted 0 before
  failure" ×20 masked the orphan pile-up.
- idc03 chronic memory pressure (~1GB avail) — separate capacity issue.
- ada-nest-heartbeats: 6 docs / 19,104 revisions — check maxRevisions.

lessons:
- A client-side timeout does NOT cancel mddb write handlers — orphaned
  deleteWhere/delete-batch calls keep running (and committing) for
  60-80+ min server-side; retries on the same cursor multiply the work.
- "Detached drain loop" hacks (while-true bash + budget flag) turned a
  slow endpoint into a self-reinforcing write-lock convoy — check for
  PPID=1 leftover loops on the target host before blaming the service.
- bbolt single-writer means ONE slow write endpoint starves ALL writes;
  read latency staying fast is the tell for a write convoy vs overload.
- deleteWhere limit=1000 was already measured ~0.5s+/doc on 2026-11-26
  (jobs/mddb/2026-11-26-sweep-pagination-keyset.yml) — it can never fit
  a 110s client window on a 592k-doc collection; pick limit so
  limit×per-doc-cost < timeout.
