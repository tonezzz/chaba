# Embedding Space Eval — gemini-embedding-2 vs nomic vs nomic+translate

Run 2026-10-15 · card `embed-space-eval` · harness `scripts/ada/embed-space-eval.py`
Data: `docs/ssot/jobs/ada/2026-10-15-embed-space-eval.json`

## Verdict

**Paid Gemini space stays — migration to nomic is not arguable on recall.**
nomic+translate reaches ~86% of gemini's recall@5 overall (14% relative
drop), well outside the card's ~5% decision band. The gap is worst exactly
where it matters: Thai queries (–23% relative on recall@5). Translation
closes about half of nomic's raw gap but not enough.

| arm | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|
| **gemini-embedding-2** (prod space) | .188 | .341 | .465 | .820 |
| nomic-embed-text raw | .128 | .247 | .330 | .625 |
| nomic + EN translate | .166 | .288 | .399 | .761 |
| mddb prod index (reference) | .163 | .339 | .450 | .760 |

### By query language

| EN (n=34) | r@1 | r@3 | r@5 | MRR |
|---|---|---|---|---|
| gemini | .222 | .373 | .489 | .813 |
| nomic | .157 | .293 | .395 | .641 |
| nomic_en | .208 | .321 | .436 | .737 |
| mddb | .187 | .373 | .474 | .735 |

| TH (n=14) | r@1 | r@3 | r@5 | MRR |
|---|---|---|---|---|
| gemini | .106 | .271 | .406 | .845 |
| nomic | .057 | .136 | .171 | .584 |
| nomic_en | .065 | .208 | .311 | .820 |
| mddb | .106 | .255 | .392 | .821 |

Top-5 overlap with the gemini ranking: nomic 21%, nomic_en 27% —
the nomic spaces retrieve materially *different* docs, not just worse.

Query-side latency (48 queries, measured): gemini/OR p50 **1.42s** p95
1.88s · nomic local p50 **0.056s** p95 1.24s · nomic_en same (+ a live
translate call ~0.5–1.5s that this eval pre-computed).

## Method

- **Corpus**: all docs from the 24 vector-searched tony collections
  (22 registry banks + personal-kk/testo; **ops-routed collections
  excluded** — `ada-ha-recall-summary-*` and `ada-ha-scenario-reports`
  are keyword-ranked in production, no vectors to migrate).
  8,261 docs fetched; 8,109 in the ranking pool after dropping
  `status: retracted` (production hides them by default).
- **Queries**: 48 real `ada_memory_search` calls from
  `experiments/query-cache-phase0/bankq-corpus-20261008.jsonl`
  (mined by `bank-router-mine.py` from ada-ha-tony journals),
  34 EN + 14 TH, spread across top_banks; utterance kept as judge context.
- **Arms**: doc-level cosine over per-arm embeddings.
  `mddb` = production reference — per-collection `/v1/vector-search`
  with the gemini query vector (mddb's own chunking + int8 index).
  Its r@5 (.450) lands within 3% of the doc-level gemini arm (.465),
  which validates the methodology against the live index.
- **nomic_en**: docs/queries containing Thai chars were translated to
  English by `gemini-3.5-flash-lite` (free key, $0) then embedded;
  EN texts reuse the raw nomic vectors. nomic used its required
  `search_document:`/`search_query:` prefixes.
- **Labels**: per query, pooled top-10 candidates of all 4 arms
  (~20-26 unique) judged relevant/not by `gemini-3.5-flash-lite`;
  48/48 labeled, mean 7.4 relevant/query. (That is why absolute
  recall@5 tops out ~0.68 — the relevant set often exceeds k;
  arm-vs-arm comparison is unaffected.)
- **Cost**: OR `google/gemini-embedding-2` for the doc corpus after
  the free tier saturated — 2.53M tokens ≈ **$0.38** (same space as
  direct -2, verified cos=1.0 per doc). All else $0.

## Findings beyond the verdict

1. **Free-tier embedding quota cannot sustain corpus-scale runs.**
   `gemini-embedding-2` free tier died after ~2.3K calls and stayed
   capped; all other family keys were 402 (depleted projects) or also
   capped. The eval needed the OR paid route (~$0.38) — fine for a
   one-off, but a full-bank migration test re-run is not free.
   *Gotcha worth keeping:* `-001` and `-2` are different spaces — a
   silent fallback mid-corpus produces an orthogonal-vector mix that
   poisons the index. The harness now pins `-2` only.
2. **nomic raw is weak on Thai even at bank level** (top_bank in
   top-5: .214 vs gemini .357) — translation helps recall but the
   translated-Thai docs still trail badly.
3. **MRR stays decent for all arms** — the single best doc usually
   still surfaces early; the loss is in coverage (recall), i.e. Ada
   would get the top fact but miss supporting context.
4. Latency is not the deciding factor: nomic is ~25x faster
   (0.056s vs 1.42s), but recall loses too much to take the win.

## Reproduce

On idc03 (`gemini-keys.env` + Ollama `nomic-embed-text` + mddb local):

```bash
set -a; source ~/.config/secrets/gemini-keys.env; set +a
export GEMINI_API_KEY=$GEMINI_API_KEY_FREE \
  MDDB_BASE_URL=http://100.102.134.91:11023 \
  OLLAMA_URL=http://100.102.134.91:11434
python3 scripts/ada/embed-space-eval.py --work /tmp/embedeval \
  --corpus experiments/query-cache-phase0/bankq-corpus-20261008.jsonl --all
```

Stages are resumable (`--fetch --select --translate --embed --prod
--label --score`). For the doc corpus use OR when free tier is capped:
`OPENROUTER_API_KEY=…` + the `run-or-docs.py` pattern from this
session's workdir (sequential calls, 8 workers).
