# Dispatch outcome — session→MDDB recall benchmark

**Task:** card `session-mddb-recall-benchmark` — prove per-session
distilled docs in MDDB are enough for team recall so sessions.db can be
pruned to active sessions.

## What was built

- `scripts/bench-recall.py` — modeled on bench-hermes.py. Flags:
  `--reps`, `--json`, `--limit`, `--lanes`, `--per-session`, plus
  `--gen-fixture` to regenerate goldens. Lanes: `mddb` (semantic_search
  on ada-ha-bank-devin-tony, status=active, topK=15, thr=0.45 — mirrors
  memory_ops.memory_search), `mddb_all_incl_superseded`, `transcript`
  (in-repo BM25 over chunked raw transcripts), `t1doc` (oracle: is the
  answer in the session's own T1 doc — measures distillation coverage),
  `surface` (session-memory.md + compactions BM25). Judge:
  gemini-3.5-flash-lite via LiteLLM gateway (litellm-chaba.env, loaded
  at runtime; strict answer-present rubric). MDDB access via JSON-RPC
  StreamableHTTP mirroring mddb-bridge.py, X-API-Key read at runtime
  from ~/.config/devin/mcp_config.json — never committed.
- `fixtures/bench-recall-fixtures.json` — the 22 sessions present in
  BOTH cli/sessions.db and the bank; 3 Q/A per session drafted by
  flash-lite from the raw transcript and ground-checked → 36 verified
  goldens.
- `reports/bench-recall-25691022.{json,md}` (force-added; reports/ is
  gitignored), `docs/ssot/jobs/models/2026-10-22-session-mddb-recall-
  bench.yml`, and a verdict comm posted to the card via board-api.

## Result — verdict: NOT yet safe to prune (T1 50.0%@3 < 80% AQ)

| lane | hit@1 | hit@3 | p50 |
|---|---|---|---|
| mddb T1 (status=active) | 33.3% | 50.0% | 0.08s |
| mddb incl. superseded raw | 38.9% | 69.4% | 0.22s |
| transcript BM25 | 75.0% | 83.3% | 0.08s |
| t1doc oracle | 41.7% | — | — |
| surface (current) | 5.6% | 5.6% | 0.04s |

Miss decomposition: 21/36 goldens absent from the T1 doc entirely —
distiller drops absolute paths, commands, commit hashes, identifiers,
counts. Only 2/36 true retrieval misses. Coverage: 22/30 ended sessions
(73.3%) have a T1 doc; bank holds 538 T1 docs. Shrink: T1 median 2.2KB
vs transcript median 1.03MB (462×).

Recommended next: add a verbatim Artifacts section (paths/commands/
hashes/ids/counts) to the devin-session distiller, re-run bench.
Interim: keep devin/<hex> transcript docs status=active → 69.4%@3.
Independent win: swap notebooklm-recall.sh to mddb semantic_search
(5.6% → 50%+).

## Verify

`python3 scripts/bench-recall.py --limit 5` (quick smoke) or full rerun;
regen fixture with `--gen-fixture`. JSON has per-question records.
Committed + pushed to dispatch/25691022-103449-build-and-run-the-session-mddb.
