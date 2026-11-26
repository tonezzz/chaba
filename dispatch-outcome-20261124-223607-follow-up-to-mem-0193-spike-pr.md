# Dispatch outcome — cms-plane-bge-golden-set-eval (MEM-0204 follow-up to MEM-0193)

## What was done

Built a golden query set + 3-arm eval for the mddb-cms :11027 embed space,
reusing the MEM-0193 spike scripts' approach and the 2026-10-15 bank
eval's pooled-cosine methodology.

**Key context drift found:** the card spec assumed gemini still served
:11027 — it doesn't. Card comms (2026-11-19) record the env swap + force
reindex already happened; :11027 is live bge-m3 today, and the idc02
:11028/:11029 scratch/bank instances are torn down. No gemini-embedded
CMS index exists anywhere, so the gemini arm is doc-level cosine over
identical candidate pools (validated methodology — prior eval found
mddb-prod within ~3% of doc-cosine on banks).

## Deliverables (committed on dispatch branch)

- `scripts/mddb/spike-cms-bge/golden_set.json` — 69 queries with
  hand-verified relevant doc keys across all 14 CMS collections
  (incl. one Thai query).
- `scripts/mddb/spike-cms-bge/golden_eval.py` — eval harness, 3 arms:
  prod-index (live :11027 vector-search), gemini-cos (:11435 proxy on
  idc03 via ssh -L forward), bge-cos (local ollama bge-m3 on tony-omen;
  embed-pool-shim :11436 was 504-degraded at eval time). Embeddings
  cached in `.embed_cache.json` (gitignored) for cheap reruns.
- `scripts/mddb/spike-cms-bge/dump_corpus.py` — corpus dump helper used
  for qrel authoring.
- `scripts/mddb/spike-cms-bge/golden_eval_results.json` — raw
  per-query rankings + metrics.
- `docs/ssot/jobs/mddb/2026-11-24-cms-bge-golden-eval.yml` — eval report
  with per-collection deltas, findings, recommendation.

## Result

Overall (n=69): prod-index r@5 0.539 / r@10 0.546 / MRR 0.541;
gemini-cos 0.954 / 0.957 / 0.942; bge-cos 0.911 / 0.952 / 0.937.

**bge-m3 is at parity with gemini-embedding-2** (−4.5% r@5, −0.5%
r@10, −0.5% MRR on identical pools) → **GO** on the embed-provider
decision; the 2026-11-19 migration is validated post-hoc.

Separate finding: prod recall is far below the doc-level ceiling
because ~250 docs have no vectors (embed-queue `dropped=910` during
pool-degraded windows; verified per-doc) and meta-only collections
(devin-kb, ssot.focus — empty contentMd) can never embed. Filed
**MEM-1336** for the coverage-gap fix (non-force reindex + drop
investigation + upstream warm-ping). Not a provider problem — gemini
would not have fixed it.

## How to verify

`python3 scripts/mddb/spike-cms-bge/golden_eval.py --skip-doccos`
reproduces the prod arm; full rerun is cheap (embeddings cached).
Report: `docs/ssot/jobs/mddb/2026-11-24-cms-bge-golden-eval.yml`.

lessons:
- Card spec said "run against gemini :11027" but :11027 was already migrated to bge-m3 on 2026-11-19 — always re-verify live embed provider before designing an A/B eval; the card's own comms had the answer.
- `/v1/get` and `/v1/search` return contentMd="" unless you pass `lang` (en/th) — docs have per-lang variants; fetch both and prefer the non-empty one.
- `/v1/search` ignores `query` (filter/list only) — there is no keyword-search endpoint; vector-search is the only relevance path.
- embed-pool-shim :11436 504s on 1500-char batches when upstreams are cold/degraded — for eval-side embedding, tony-omen local ollama (`bge-m3:latest` on 127.0.0.1:11434) is faster and deterministic; same model the shim races.
- gemini-ollama-proxy :11435 binds localhost on idc03 only — `ssh -L 11435:127.0.0.1:11435 idc03` makes it reachable; port may already be forwarded.
