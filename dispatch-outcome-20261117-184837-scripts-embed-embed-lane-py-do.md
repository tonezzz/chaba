# Dispatch outcome — embed-lane-banks-search-pagination

## What changed

`scripts/embed/embed-lane.py::_docs` now paginates `/v1/search` by
`offset` in `PAGE=1000` steps until a short page — the server caps any
`limit` at 1000 docs, so the old single `limit=10000` call silently
truncated every collection >1000 docs on BOTH sides of the banks diff
(source listing AND target `have` set). Loop follows the
`scripts/devnest/mddb_probe.py:cmd_expired` pattern, plus a guard that
breaks if a full page returns only already-seen keys (protects against
an offset-ignoring server looping forever). Trail file:
`docs/ssot/jobs/mddb/2026-11-17-embed-lane-banks-search-pagination.yml`.
Committed on `dispatch/20261117-184837-...` (33bec4adf2); not pushed.

## Backfill result

Ran `embed-lane.py banks` twice from this worktree on idc02:

- pass 1: **3115 docs delivered, 0 failed** — devin-handoff 1939,
  infrastructure-ssot 1132, ada-cms-pages 25, devin-tony 19.
  Queue throttle engaged (paused /add at depth>=3000, resumed on drain).
- pass 2: **198 docs, 0 failed** — devin-handoff is live-written and
  gained +197 during pass 1 (+1 cms-pages).

## Verification

Fresh key-set diff source→mddb-embed :11028 over all 24 BANK_COLLS:
**0 missing docs with `contentMd` in every collection** (previously
-1432 devin-handoff, -1132 infra-ssot, -22 cms-pages, …). Queue
`dropped=0` throughout; depth ~1300 draining async through the
embed-pool at end of session.

Caveat recorded in the trail file: 142 source docs have no `contentMd`
(e.g. devin-kb 9, chaba-docs 15, ada-ha-bank-github 15) — uncopyable by
design and always show as a raw key-set diff. Future audits should diff
content-bearing docs only.

## Side observation (not blocking)

The embed-pool upstream (idc03 :11436 → ollama bge-m3) returned 504
bursts under backfill load; mddb-embed's circuit breaker requeues
(maxAttempts=50), so drain slowed to ~1 job/min while saturated. No
drops; the queue finishes unattended. Worth watching only if the daily
job starts racing maxAttempts.

## How to verify

- `python3 scripts/embed/embed-lane.py banks --dry-run` → `todo≈0`
  for every collection.
- `curl -s -X POST http://100.123.163.11:11028/v1/vector-stats -d '{}'`
  → `queue.dropped == 0`; `embedded_documents` → `total_documents`.
- Unit tests: `python3 -m unittest tests.embed.test_embed_lane` (7/7 ok).
