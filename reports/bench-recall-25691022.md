# Session→MDDB Recall Benchmark — 2026-10-22

Card: `session-mddb-recall-benchmark`. Question: are per-session
distilled docs in `ada-ha-bank-devin-tony` (`devin-session/<name>`, the
T1 tier) enough for team recall so `sessions.db` can be pruned to active
sessions?

**Verdict: NO — not yet.** T1 recall hits 50.0% @3 vs the 80% bar. But
the bottleneck is the *distiller*, not retrieval: an oracle check on the
session's own T1 doc finds the golden answer only 41.7% of the time.
Semantic retrieval over the bank actually out-performs the oracle
(answers frequently live in sibling sessions' docs — the same task is
re-run across sessions). Fix the distiller's artifact coverage, re-run
this bench.

## Method

- Fixture `fixtures/bench-recall-fixtures.json`: the 22 sessions present
  in *both* `~/.local/share/devin/cli/sessions.db` (raw transcript via
  `message_nodes`, user+assistant text per the FTS-trigger rule) and the
  MDDB bank (T1 doc). 3 Q/A pairs generated per session by
  `gemini-3.5-flash-lite` from the raw transcript, then each pair
  ground-checked against the transcript by the same model —
  36 verified goldens kept (teammate-style: outcome of X, root cause of
  Y, which file/card Z, where a decision landed).
- Judge: one fixed `gemini-3.5-flash-lite` via the LiteLLM gateway
  (`litellm-chaba.env`), strict answer-present rubric, temp 0.
- Retrieval scored hit@1 / hit@3 + p50 latency (retrieval only, judge
  excluded).

## Results

| lane | what it measures | hit@1 | hit@3 | p50 |
|---|---|---|---|---|
| `mddb` | T1 recall — `semantic_search` status=active, topK=15, thr=0.45 (mirrors `memory_ops.memory_search`) | 33.3% | **50.0%** | 0.08s |
| `mddb_all_incl_superseded` | same but the superseded `devin/<hex>` raw-transcript docs stay searchable | 38.9% | 69.4% | 0.22s |
| `transcript` | BM25 over chunked raw transcripts of the 22 fixture sessions | 75.0% | **83.3%** | 0.08s |
| `t1doc` | oracle: is the answer in the session's own T1 doc at all | 41.7% | — | — |
| `surface` | today's recall: `session-memory.md` tail + `compactions/*.md`, BM25 | 5.6% | 5.6% | 0.04s |

## Coverage (delete-gate viability)

- sessions.db on this host: 103 sessions, 30 hidden(ended).
- With a `devin-session/<name>` doc: **22/103 = 21.4% overall;
  22/30 = 73.3% of ended sessions.** 8 ended sessions have no T1 doc —
  the distill-verify gate would block their prune.
- Bank holds 538 `devin-session/*` docs total (all hosts, incl. already
  deleted sessions) — coverage on the archive side is healthy.

## Bytes / session (the shrink)

- T1 doc: median **2.2 KB**, mean 2.6 KB.
- Raw transcript (`message_nodes` sum): median **1.03 MB**, mean 36 MB
  (one outlier session carries 746 MB of pasted dumps).
- Median shrink: **462×**.

## Where the misses are

Distiller misses (21/36 goldens absent from the T1 doc entirely —
retrieval can never find them). The dropped fact classes:

- **absolute paths**: worktrees, SSOT files (`docs/ssot/infrastructure/
  ssot.mcp.yml` style), kanban card files, env/token file paths,
  report/scenario output paths
- **commands**: e.g. `chmod +x ~/.config/devin/mcp-scripts/*.sh`
- **commit hashes / branch names**: `623bd2d`, dispatch branch names
- **identifiers**: collection names, counts (113 docs superseded),
  view names (`chaba-home/g3`), lock-file paths
- **bug specifics**: e.g. the variable-shadowing root cause

True retrieval misses (T1 had the answer, `semantic_search` top-3 still
missed): only 2/36 — both were repeat-run sessions (MCP-tools
verification on tony-dell) where a sibling session's near-identical doc
outranked the right one. Retrieval is essentially fine.

## Recommendation

1. **Do not prune on T1 alone** — 50% vs the 80% AQ.
2. Enrich the T1 distiller template (`sync-devin-summaries.py` /
   whatever writes `devin-session/*`): add a verbatim **Artifacts**
   section — every absolute path touched, commands run, commit hashes,
   card ids, hostnames, ports, counts — then re-run this bench.
3. Interim option the bench supports: keep the `devin/<hex>`
   raw-transcript docs `status=active` (don't supersede) — hit@3 rises
   to 69.4% with zero new pipeline. Cheaper than full T0 transcripts in
   sessions.db, though it gives up part of the 462× shrink.
4. Today's flat-file recall (`session-memory.md` + compactions) answers
   5.6% — MDDB semantic recall is already ~9× better even in its current
   state; swapping `notebooklm-recall.sh` to `semantic_search` is a win
   independent of the prune decision.

## Caveats

- 22 sessions / 36 goldens — solid signal, not exhaustive. Goldens are
  model-generated then ground-checked; they skew toward facts stated in
  the transcript head (gen prompt cap 48 KB) and teammate-style "which
  path/command" questions.
- Transcript lane searched only the fixture corpus (2861 chunks); a
  production-wide corpus may score lower.
- `t1doc` oracle < `mddb` hit@3 is expected: sibling docs often carry
  the same fact (repeat tasks).
