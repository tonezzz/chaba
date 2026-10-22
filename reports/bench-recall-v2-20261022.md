# bench-recall v2 — enriched T1 distiller (Artifacts section) re-benchmark

Card: `session-mddb-recall-benchmark` · Runner: idc02 · 2026-10-22 · fixture: same 22 sessions / 36 goldens as run 1 · judge: gemini-3.5-flash-lite (direct)

## What changed since run 1

- `scripts/ada/session_artifacts.py` — deterministic miner: transcript → `## Artifacts` markdown (paths, commands, commits/branches, card/task/doc-key ids, hosts, collections, URLs, sizes/counts, error lines). No LLM; the facts are verbatim from the transcript, so nothing is invented.
- `scripts/ada/sync-devin-summaries.py --enrich` — production hook: appends the Artifacts section to `devin-session/<name>` docs while the session still lives in sessions.db (pre-delete window).
- `bench-recall.py` — REST `/v1` transport (`MDDB_REST_URL`, runs anywhere on the tailnet, writes go to the leader), corpus sidecar, lanes `mddb_v2` / `t1v2` / `t1bm25` / `hybrid` / `hybrid_t2`, `--write-v2` / `--cleanup-v2`, per-hit key attribution.

## Result

| lane | hit@1 | hit@3 | note |
|---|---|---|---|
| mddb semantic, T1 **v1** (current bank) | 36.1% | **50.0%** | clean baseline, reproduces run 1 exactly |
| mddb semantic, T1 **v2** enriched | 55.6% | **66.7%** | 19/24 hits were v2 docs |
| keyword BM25 over T1-v2 whole docs | 52.8% | 52.8% | artifacts are shared vocabulary — whole-doc granularity can't discriminate |
| hybrid T1 semantic ∪ T1 keyword (6 items) | 55.6% | 69.4% | union judged over ≤6 |
| **hybrid T1 semantic ∪ T2 transcript keyword (6 items)** | 55.6% | **91.7%** | T1 warm + T2 cold keyword fallback |
| transcript BM25 alone (T2) | 77.8% | 83.3% | reference ceiling |
| t1doc oracle — fact in own v1 doc | 41.7% | — | distiller coverage, run-1 repro |
| **t1v2 oracle — fact in own v2 doc** | **86.1%** | — | enrichment more than doubles capture |

Bytes/session: v1 T1 median 2.2KB → v2 median ~4.7KB (still ~220× smaller than transcript median 1.03MB).

## Miss decomposition (mddb_v2, 12/36 misses)

- 4 misses: fact still absent from v2 doc (qualitative root-cause/decision goldens the artifact miner can't reach).
- 8 misses: fact IS in v2 doc (oracle ✓) but the doc doesn't rank top-3 — 6 of 8 didn't even rank top-15. Single-vector doc embedding is the limit: a 4-5KB doc covering ~40 distinct artifacts can't win a semantic top-3 on one buried fact.
- Scoped semantic (`subject=devin-session-summary` filter) doesn't fix ranking either: 21/36 top-3.
- hybrid_t2 residual misses: `awake-sheet#1`, `brave-squirrel#2`, `confusion-subway#1` (2 absent from v2, 1 unranked).

## Verdict

**Ship the enriched distiller — it's validated** (coverage 41.7%→86.1%, deterministic, ~2.5KB/session added). But **T1-semantic alone still fails the 80% AQ (66.7%)** — the constraint is retrieval, not content. The tiered design holds **if recall is hybrid**: T1 semantic (+ `session_name` meta-scoped fetch, 86.1% on session-addressable questions) **with a T2 keyword fallback = 91.7%**, comfortably above AQ. Implication: sessions.db can prune to T0 only if T2 transcript archives stay *locally grep-able* (~text .md files, not GDrive-only) and the recall path runs both retrievals. `mddb` has no text search (`/v1/search` ignores `query`); options: local BM25 over the T2 dir in the recall hook, or an FTS endpoint in the mddbd fork.

## Verify

`python3 scripts/bench-recall.py --lanes mddb mddb_v2 t1doc t1v2 transcript t1bm25 hybrid hybrid_t2 --json reports/bench-recall-v2-20261022.json` (runner needs transcripts — `scripts/bench/pull-session-transcripts.sh <fixture-host>`; judge key from `~/.config/secrets/gemini-api-key.env` or LiteLLM gateway). Raw: `reports/bench-recall-v2-20261022.json`.
