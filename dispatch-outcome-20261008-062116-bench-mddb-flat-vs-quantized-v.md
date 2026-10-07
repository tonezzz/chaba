# Dispatch outcome — lab-mddb-quantized

Card: `lab-mddb-quantized` · Session: dispatch-wt-20261008-062116 · Repo: chaba (this worktree)

## What was done

Benched mddb flat vs quantized vector indexes as the card asked, on the
follower node (idc01) with leader and follower serving throughout:

- Consistent DB copy via `POST /v1/backup` on the follower (a plain `cp`
  produced a torn file — replication writes race the copy; the file opens
  but bucket walks panic).
- Scratch `mddb` container (`localhost/mddb:2.15.4-lsn`, the prod image) on
  idc01, `MDDB_MODE=wr`, `MDDB_VECTOR_ALGORITHMS=flat,quantized`, HTTP on
  `100.74.146.0:11130`, no embedding provider — all queries used
  `queryVector` from stored vectors (vdump tool, standalone bolt+decoder
  for the `vectors` bucket's v1 float32 / v2 quantized record formats).
- 9 collections x 25 queries (20 stored + 5 synthetic midpoint+noise).
  Doc-level recall@10 vs flat-served baseline, plus a flat-vs-flat2 control
  pass for the tie-churn noise floor and an oversample=10 probe.
- Config states via `PUT /v1/collection-config` + restart: prod, all-flat,
  int8-in-mem, int8+diskOnly, int4+diskOnly.
- Bench container + 8 GB scratch data removed afterwards; follower
  untouched (still `active`).

## Verdict — hypothesis REJECTED on all three card metrics

- recall@10 vs flat (prod path int8+diskOnly): .62–.94, mean .87
  (threshold .95). Raw int8 ANN .70; oversample=10 .87; int4 .68.
  Synthetic/out-of-corpus queries score lower still.
- RSS/heap: no reduction — `heap_inuse` 1.20 GB flat vs 1.23 GB
  int8+diskOnly (vector index is a small slice vs FTS+bolt; threshold 25% FAIL).
- Latency: worse on large colls — host-logs 225 vs 111 ms, devin-tony
  89 vs 50 ms (scalar int8 cosine vs SIMD f32 + rescore disk reads).
- On-disk storage unchanged (diskOnly keeps float32 vectors in bolt).

## Recommendation (in card note)

Revert the 6 production int8+diskOnly collections to float32
(`ada-ha-bank-devin-tony`, `ada-ha-events-michael`, `ada-ha-events-tony`,
`ada-ha-scenario-reports`, `host-logs`, `yomi-digest`) — needs a leader
collection-config PUT or panel change, i.e. a production write Tony must
approve/trigger.

## Deliverables

- Card `note:` updated with verdict + recommendation (committed on the
  dispatch branch).
- Decision record: `docs/ssot/jobs/mddb/2026-10-08-mddb-flat-vs-quantized-bench.yml`.
- Artifacts: `reports/bench-mddb-quantized-artifacts-2026-10-08.tgz`
  (untracked — `reports/` is gitignored): driver scripts, per-state served
  rows, exact-truth sets, scorecard.json.
- Scorecard comment to board-api: posted via background retry loop —
  tony-dell went unreachable mid-session (tailscale ping + LAN ssh both
  dead, ARP alive). If the loop exhausted before recovery, the comment
  text is in the retry script + this file and should be re-posted.

## Side findings worth follow-up

- flat-vs-flat result churn across restarts (.92 mean) — score-tie bands +
  unstable sort + map order; deterministic tiebreak would stabilize top-10.
- int8 cosine is scalar Go vs flat SIMD — quantization saved bytes, not
  cycles, on this hardware.
- `/v1/backup` is the only safe way to copy a live DB for offline work.
