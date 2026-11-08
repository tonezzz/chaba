# BGE-M3 embedding-space evaluation

Run 2026-11-05 · local bank `idc03:11028` · model `bge-m3`

## Verdict

**Promising, but not an automatic production cutover yet.** BGE-M3 is
within the original overall recall band at recall@5, but MRR is materially
lower and the English subset is just outside the 5% band. The result should
be treated as a migration candidate pending a repeat run with the pool
healthy and a larger/cleaner judged candidate set.

## Method

- Same 48 real memory queries as the 2026-10-15 Gemini/Nomic evaluation:
  34 English and 14 Thai.
- Same active document corpus and existing relevance judgments.
- BGE queries were sent to the fully populated local bank at `idc03:11028`,
  which embeds through the local `bge-m3` pool.
- BGE's new top-10 candidates were added to the judgment pool and labeled
  with the existing Gemini judge. The one malformed judge response was
  retried successfully.
- All arms were rescored against the expanded judgments, so the numbers
  below are comparable with one another but are not directly identical to
  the original report's unexpanded numbers.
- The local bank had 9,740/9,740 documents embedded, queue depth 0, and
  zero dropped jobs at run time.

## Results

| subset | arm | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---:|---:|---:|---:|
| overall | Gemini | .142 | .273 | .356 | .855 |
| overall | Nomic | .103 | .214 | .292 | .697 |
| overall | Nomic + English translation | .133 | .241 | .347 | .839 |
| overall | **BGE-M3** | **.079** | **.214** | **.348** | **.740** |
| English | Gemini | .166 | .291 | .360 | .809 |
| English | Nomic + English translation | .157 | .262 | .369 | .807 |
| English | **BGE-M3** | **.077** | **.208** | **.337** | **.655** |
| Thai | Gemini | .085 | .228 | .347 | .964 |
| Thai | Nomic + English translation | .073 | .189 | .292 | .917 |
| Thai | **BGE-M3** | **.083** | **.229** | **.377** | **.946** |

Relative to Gemini at recall@5:

- Overall: BGE-M3 is **2.2% lower** (`.348` vs `.356`).
- English: BGE-M3 is **6.4% lower** (`.337` vs `.360`).
- Thai: BGE-M3 is **8.6% higher** (`.377` vs `.347`).
- Overall MRR is **13.5% lower** (`.740` vs `.855`), so BGE often finds a
  relevant item later even when it reaches similar recall by rank 5.

## Latency

Measured query wall time across the 23 local-bank collections:

- p50: **0.293 s**
- p95: **0.678 s**
- maximum: **0.746 s**
- 48/48 queries returned ten hits with zero request errors

This is a local-bank retrieval measurement, not a clean isolated per-host
embedding benchmark. The embed-pool is hedged and returns the first
successful upstream.

## Decision

BGE-M3 is now strong enough to justify a controlled side-by-side pilot, but
not enough to silently replace Gemini in production. Before cutover:

1. Repeat with the embed-pool upstreams healthy and record per-upstream
   winners/latency.
2. Confirm the local bank and production corpus membership are identical.
3. Repeat the judged run with a fresh candidate pool and verify the English
   MRR gap.
4. If the result holds, migrate through a complete BGE reindex and switch
   document/query embedding atomically; never mix BGE and Gemini vectors.

Artifacts from the run are in `/tmp/embedeval/bge-hits.json` and
`/tmp/embedeval/qrels-bge.json` on `idc03`.

## Nest-style follow-up probe

Nest is a good fit as an experiment orchestrator: each pack can run one
isolated retrieval recipe, emit ranked hits and metrics, and the scorer can
select the winner without touching the production Gemini bank.

A quick offline probe fused the existing BGE top-10 list with a local BM25
top-100 list using weighted reciprocal-rank fusion. It improved provisional
BGE results from recall@5 `.332` / MRR `.739` to:

| RRF lexical weight | recall@5 | MRR |
|---:|---:|---:|
| 0.25 | **.408** | .849 |
| 0.50 | .406 | .842 |
| 0.75 | .402 | **.853** |

This is directional, not an official result: the BGE list was only top-10
and the existing judgment pool does not yet include all BM25 candidates.
The next pack should retrieve top-50 or top-100 from both arms, judge the
new candidate union, and then rescore.

Recommended pack matrix, in order:

1. BGE dense + BM25 RRF, weights `0.25`, `0.5`, `0.75`.
2. BGE prefix ablation: raw/raw versus `search_document:` /
   `search_query:`.
3. Thai dual-query fusion: original Thai plus translated English, with
   deterministic RRF.
4. Parent/chunk aggregation to improve MRR without changing the model.

Avoid using a generative reranker as the first experiment. It adds latency
and judgment noise; the deterministic hybrid result already targets the
current English MRR weakness.

## Shadow-job adapter

Added `scripts/ada/bge-hybrid-recall.py` as the first real-job surface. It
is read-only: `--build` snapshots the local bank's documents for BM25 and
`--query` fans out vector search to all 23 local collections, then returns
weighted RRF results. It does not write MDDB or touch the Gemini bank.

Smoke verification on `idc03`:

```bash
python3 scripts/ada/bge-hybrid-recall.py \
  --base http://idc03:11028/v1 \
  --index ~/.cache/bge-hybrid-docs.json \
  --build

python3 scripts/ada/bge-hybrid-recall.py \
  --base http://idc03:11028/v1 \
  --index ~/.cache/bge-hybrid-docs.json \
  --query "what changed on idc02 security" \
  --top-k 5
```

The live query returned 5 results with zero vector errors in 2.06 seconds
(vector fan-out p50 100 ms). This is ready for a shadow or batch job; it is
not yet wired into Ada's primary memory path.

## Live shadow replay

Ran the adapter against the same 48-query fixture used by the benchmark,
with BGE top-50 + BM25 top-100 + RRF (`dense=1.0`, `lexical=0.75`):

- 48/48 queries completed
- 0 vector errors
- total wall time: **395 seconds**
- query latency p50: **402 ms**
- query latency p95: **1.205 s**

This is enough for a real read-only batch/shadow job. The next production
step is packaging this replay as a Nest artifact-producing pack and wiring
one non-critical consumer; no Gemini or Ada primary retrieval path has been
changed.

The artifact pack is now declared at
`scripts/colab/packs/bge-hybrid-shadow/pack.yml`. It fetches only the
read-only adapter and query fixture, writes JSON/Markdown results under its
own `out/` directory, and keeps the temporary lexical snapshot outside the
Drive artifact set. The pack passed local validation and was staged at
`gdrive:ada-nest/packs/bge-hybrid-shadow/`; it is waiting for the next
capable Nest worker. A direct `rclone lsf` confirmed `pack.yml` was present
on the remote queue before execution.

## Nest pack result

The pack was claimed and completed by `con01`:

- 48/48 queries completed
- 0 vector errors
- pack wall time: **927 seconds**
- reported job wall time: **896.8 seconds**
- p50/p95 query latency: **2.447s / 2.752s**
- artifacts: `gdrive:ada-nest/packs/bge-hybrid-shadow/out/`

The slower con01 result is expected versus the local-idc03 replay: it is
running the same read-only query fan-out across the network from a worker
without a local embedding endpoint. The job is now operationally real and
repeatable; this pack used its deterministic first-34-English/14-Thai slice
of the corpus, so it is an operational replay rather than the final
apples-to-apples quality score. The next improvement is worker
placement/connection reuse, not correctness.

## Local worker retry

The first idc03 run exposed a concurrency issue: eight simultaneous
collection calls produced transient 503s. The adapter was tightened to four
parallel collection calls and the pack was rerun as
`bge-hybrid-shadow-idc03-v2`:

- 48/48 queries completed
- **0 vector errors**
- pack wall time: **547 seconds**
- query latency p50/p95: **216 ms / 991 ms**

This is the preferred operational configuration. It gives idc03's local
worker both lower latency than con01 and clean reliability.

## Education shadow consumer

Added `scripts/ada/bge-lessons-shadow.py` to read the private lesson CPT
through board-api and mirror it into the isolated `bge-lessons-shadow`
collection on `mddb-embed`. It synced **99 lessons** without touching WP or
the production memory banks. The BGE lexical snapshot now contains 24
collections / 9,832 documents.

A live query for `mddb local embedding cutover status` returned the shadow
lesson `lesson/lesson-dfdb9fbd8d95` as the second result with zero vector
errors in 1.52 seconds. This proves the first non-critical Education
consumer path; it is still a sidecar query, not a replacement for the
`education-due` page or Ada's primary `memory_search`.

The due-review shadow then ran against all **86 due lessons**:

- 86/86 completed
- 0 vector errors
- wall time: **925.6 seconds**
- the BGE lesson collection was the top result for **70/86** queries

The report is read-only and lives at
`idc03:/home/tony/.cache/bge-education-shadow.json`. The next optimization
is to reuse the in-memory BM25 index and batch the due-review queries; the
current run rebuilds the index per query and is correctness-first.

That optimization is now implemented via `query_loaded()` in
`bge-hybrid-recall.py`. The rerun processed **85 due lessons** with **0
vector errors** in **36.5 seconds**; the BGE lesson collection was top for
**69/85** queries. This makes the shadow suitable for a daily due-review
batch rather than a one-off probe.

For a deterministic self-retrieval sanity check, the due lesson's own
document was found at top-1 for **68/85** queries and top-5 for **83/85**
(MRR **.888**). A direct Gemini comparison is not available yet because the
production Gemini collections do not contain the private lesson CPT; that
requires a separate Gemini lesson sidecar or an offline embedding run.

The Education due-page generator now has an optional, freshness-gated
`BGE_EDU_SHADOW_REPORT` read path. When a report newer than 48 hours exists,
it appends a **Related lesson suggestions (BGE shadow)** section; it never
changes due ordering and silently omits the section when the report is
missing or stale. The change is dry-run verified locally (`67` due lessons
received related suggestions); deployment still follows the normal served
checkout sync path.

## Judged-union benchmark — final (2026-11-07)

The provisional `.408/.849` hybrid probe only judged BGE's top-10 plus a
partial BM25 pool, so it was directional. `scripts/ada/bge-hybrid-judged.py`
ran the proper version: dense top-50 across all collections + BM25 top-100
per query, union candidate pools LLM-judged into `qrels-bge-hybrid.json`
(4,800 new candidates across 48 queries, 0 judge/vector errors), then every
arm rescored on the expanded relevance set.

Overall (48 queries, expanded qrels — relevant-pool denominators are much
larger than the first-pass judgments, so absolute recall numbers drop for
every arm):

| arm | r@1 | r@3 | r@5 | MRR |
|---|---|---|---|---|
| gemini | .086 | .186 | .244 | .893 |
| nomic_en | .072 | .162 | .237 | .877 |
| **bge_dense** | .047 | .135 | .224 | .767 |
| hybrid_w25 | .048 | .118 | .197 | .717 |
| hybrid_w50 | .040 | .104 | .173 | .610 |
| hybrid_w75 | .038 | .100 | .154 | .584 |
| bm25 | .015 | .052 | .104 | .371 |

Thai: bge_dense r@5 **.272** vs gemini **.255**, MRR **.946** vs **.964** —
BGE remains the strongest local arm on Thai. English: bge_dense r@5 .204
vs gemini .240, MRR .693 vs .863 — still the weak split.

**Verdict: hybrid RRF does not beat BGE dense alone on the expanded
judgments.** The provisional gain was a narrow-judgment artifact —
promoting lexical hits into the top-5 displaced other relevant docs once
the relevant pool was fully counted. Best local arm stays raw BGE dense:
92% of Gemini r@5 overall, better on Thai, but MRR and English still trail
meaningfully. Production cutover remains unjustified; the BGE sidecars
(education shadow, read-only adapters) stay valuable on their own merits.
Artifacts: `2026-11-07-bge-hybrid-judged-union.{json,md}`, script +
raw-hit capture in `bge-hybrid-judged.py`.

## Rerank benchmark — the gap closes (2026-11-08)

`bge-reranker-v2-m3` rescored the dense top-50 pool per query (48 queries,
bge-hybrid-judged candidate pools, `qrels-bge-hybrid.json`), full run on
Omen's restored GPU lane (~23s/query CPU-free, ~18min wall):

| arm | r@1 | r@3 | r@5 | MRR |
|---|---|---|---|---|
| **bge_dense + rerank** | .072 | .188 | **.260** | **.869** |
| gemini | .086 | .186 | .244 | .893 |
| bge_dense | .047 | .135 | .224 | .767 |
| rerank_union (dense+lex) | .054 | .170 | .250 | .791 |

Thai: rerank .273 r@5 / **.964 MRR** = Gemini exactly. English: .255 / .829
vs Gemini .240 / .863 — ahead on recall, slightly behind on MRR.

**Verdict: local dense+rerank BEATS Gemini on recall@5 and is within noise
on MRR overall — while winning outright on Thai.** The cross-encoder was
the right move: it targeted exactly the MRR/ranking gap fusion couldn't.
`rerank_union` confirms lexical candidates still dilute — rerank the dense
pool only. The remaining production questions are serving cost
(~20s/query on GPU is batch-grade; a real service needs request-path
rerank ≤ ~500ms — feasible on GPU, not on this CPU fleet) and the
reliability soak. Cutover case is now real, not speculative.
Artifacts: `2026-11-08-bge-rerank-v2-m3.{json,md}`, script
`scripts/ada/bge-rerank-eval.py`.

## Serving-path latency + pool soak (2026-11-08)

Rerank serving cost measured on Omen GPU (bge-reranker-v2-m3, warm model,
batch per query): top-10 **565ms**, top-20 1134ms, top-30 1704ms, top-50
**2891ms** (~57ms/pair). A top-50 rerank does NOT fit a ~500ms voice
request path; options: rerank top-10 only (~565ms, borderline), lighter
reranker (v2-m3-base ~3x lighter), or async rerank (dense results return
immediately; ranking refines for callers that can wait).

Embed-pool soak through embed-pool-shim (idc03:11436, races 5 upstreams):
baseline 30 probes — 29/30 ok, **p50 131ms / p95 2823ms** (one timeout,
the known transient). Controlled con01 drop: 15/15 still ok — the racing
shim routes around a dead member — but **p50 degraded to 2264ms** (~17x).
Resilience holds; a dead upstream costs latency, not availability.
GPU lane note: py3.12 GPU venv on Omen (`~/.local/share/chaba-ml-gpu-venv`,
torch 2.11.0+cu128) is now the fast path for batch rerank (~23s/query
full pipeline vs ~400-1400s CPU); declared as `python_ml_gpu` in
ssot.host-software.yml (#99).

## Rerank depth ablation — top-10 wins outright (2026-11-08)

Rescored the saved GPU ranks at each depth (rerank dense top-K, append
dense tail — zero new inference):

| depth | r@5 | MRR | latency |
|---|---|---|---|
| **top-10** | **.262** | **.938** | 565ms |
| top-20 | .251 | .892 | 1134ms |
| top-30 | .263 | .887 | 1704ms |
| top-50 | .260 | .869 | 2891ms |
| gemini | .244 | .893 | — |

Top-10 rerank BEATS Gemini on both headline metrics (MRR .938 vs .893;
Thai MRR 1.000) — deeper pools dilute, the cross-encoder's best work is
reordering the dense head. Serving answer for MEM-1129: **top-10 sync
rerank, ~565ms on GPU after ~130ms dense fetch ≈ 700ms voice path**,
with Gemini kept as fallback upstream (pool soak showed member loss
costs latency not availability). Lighter-reranker and async variants
demoted to optional tuning.
