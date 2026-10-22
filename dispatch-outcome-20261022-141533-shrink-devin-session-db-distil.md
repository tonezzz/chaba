# Dispatch outcome — session→MDDB recall benchmark v2 (enriched distiller)

**Card:** `session-mddb-recall-benchmark` (round 2 — executes the
`distill-then-rerun` recommendation from the run-1 verdict).

## What was built

- `scripts/ada/session_artifacts.py` — deterministic miner:
  transcript → `## Artifacts` markdown (paths, commands, commit/branch,
  card/task/mddb-key ids, hosts, collections, URLs, sizes/counts, error
  lines). No LLM — verbatim facts only.
- `scripts/ada/sync-devin-summaries.py --enrich` — production distiller
  hook: appends the Artifacts section to `devin-session/<name>` docs
  while the session still lives in sessions.db.
- `scripts/bench-recall.py` — now runs on any tailnet host: REST `/v1`
  transport (`MDDB_REST_URL`, MCP still preferred where configured),
  `--corpus` sidecar for transcripts not in the local sessions.db, lanes
  `mddb_v2`, `t1v2` (oracles), `t1bm25`, `hybrid`, `hybrid_t2`,
  `--write-v2`/`--cleanup-v2`, per-hit key attribution (`hit_keys`,
  `hit_v2`).
- `scripts/bench/pull-session-transcripts.sh <host>` — rebuilds the
  corpus sidecar (read-only ssh + remote python on the fixture host).
- `reports/bench-recall-v2-20261022.{md,json}` (force-added),
  `docs/ssot/jobs/models/2026-10-22-session-mddb-recall-bench-v2.yml`.
- Pulled the 22 fixture transcripts from tony-dell →
  `reports/bench-recall-corpus/transcripts.json` (gitignored, contains
  session content — intentionally NOT committed).

## Result — v2 distiller validated; T1-semantic alone still fails AQ; hybrid clears it

| lane | hit@1 | hit@3 |
|---|---|---|
| mddb semantic, T1 **v1** baseline | 36.1% | 50.0% (reproduces run 1) |
| mddb semantic, T1 **v2** | 55.6% | 66.7% |
| keyword BM25 over v2 whole docs | 52.8% | 52.8% |
| hybrid T1 semantic ∪ T1 keyword (≤6) | 55.6% | 69.4% |
| **hybrid T1 semantic ∪ T2 keyword (≤6)** | 55.6% | **91.7%** |
| transcript BM25 (T2) | 77.8% | 83.3% |
| oracle: fact in own v1 doc | 41.7% | — |
| oracle: fact in own **v2** doc | **86.1%** | — |

Verdict posted to card: ship the enriched distiller (coverage 42%→86%);
do **not** rely on T1-semantic alone for recall (66.7% < 80% AQ — the
constraint is now retrieval: 8/12 misses are present-but-unranked);
prune to T0+T1+T2 is safe only with **hybrid recall** (T1 semantic /
`session_name`-scoped + T2 keyword = 91.7%), which requires T2
transcript `.md` archives to stay locally grep-able. mddb has no text
search (`/v1/search` ignores `query`) — a local BM25 layer or an mddbd
FTS endpoint is needed for single-surface T1 recall.

## Notes / issues found

- The 22 `devin-session-v2/<name>` bench docs were written to
  `ada-ha-bank-devin-tony` (leader, status=active) for the mddb_v2 lane
  and **deleted after the run** (`--cleanup-v2` verified: 22 deleted).
- **Board issue:** `POST /request` to board-api failed — the served card
  file (`docs/ssot/kanban/cards/session-mddb-recall-benchmark.yml` on the
  live checkout) contains an unresolved merge conflict
  (`<<<<<<< HEAD` around the `updated:` field). Comments still post;
  the requests list can't be parsed/written until the conflict is
  resolved on the served checkout.
- The earlier `mddb` lane in the merged JSON was contaminated by the
  smoke-run v2 docs; the final baseline was re-measured clean (50.0%).

## Verify

`python3 scripts/bench-recall.py --lanes mddb mddb_v2 t1doc t1v2 transcript t1bm25 hybrid hybrid_t2 --json reports/bench-recall-v2-20261022.json`
(on a non-fixture host first run
`scripts/bench/pull-session-transcripts.sh tony-dell`; judge key from
`~/.config/secrets/gemini-api-key.env` or the LiteLLM gateway).
Committed on `dispatch/20261022-141533-shrink-devin-session-db-distil`
as `dad43563`.
