# Dispatch outcome — ada-opencode-result-review-pilot (ADA-1041)

Commit `e274a6946f` on `dispatch/20261124-192642-related-to-ada-1010-canonical-` (not pushed).

## What was built

Evaluation-only Ada reviewer path for OpenCode result bundles — a review
plane, NOT an `executor=ada` lane (`ada` stays out of
`ada_job_envelope.EXECUTORS`; deterministic gates remain hard).

- `scripts/devnest/ada_result_review.py` — `bundle` (assembles the
  allowlisted `ada-review-bundle/1` from an opencode-lane/shadow run
  dir: artifact bytes+sha256, verifier verdict+checks, summarized
  tool-call audit; raw trace/stderr/verifier source/labels/secrets
  structurally excluded), `review` (one bundle → schema-validated
  `ada-opencode-review/1` verdict), `eval` (frozen corpus → metrics).
  Backends: `litellm` (baseline), `ada-ws` (real Ada text lane,
  gated by `ADA_REVIEW_ALLOW_LIVE=1`), `replay`, `stub`.
- `schemas/ada-review-bundle.schema.json`,
  `schemas/ada-opencode-review.schema.json` — draft 2020-12 contracts.
- `evals/ada-review/cases/` — 8 frozen cases: 2 clean real runs, 1 real
  FAIL run (p1-ssot-research-201939), 5 seeded defects (hash mismatch,
  false claim, scope violation, missing evidence→needs_human, spec-gap
  provenance). `expected.yml` is held out of the bundle.
- `evals/ada-review/PROCEDURE.md` — usage + boundaries.
- `tests/devnest/test_ada_result_review.py` — 8 tests, all pass.
- `docs/ssot/jobs/devnest/2026-11-24-ada-opencode-result-review-pilot.yml`
  — full job record with results/gates.

## Results (shadow mode, first pass)

- replay oracle: 8/8 expected match (plumbing proof).
- litellm `gemini-3.5-flash-lite`: recall 0.5, expected 5/8 — missed the
  three subtle seeded defects the deterministic gate can't see.
- litellm `chat` (gemini-3.5-flash): **8/8 expected match, critical
  recall 1.0, FP 0, citation quality 1.0, p50 ~9.2s** — report at
  `evals/ada-review/reports/20261124-130138-ada-review-eval-litellm.md`
  (result_ref for the card).

## Not done / gates

- Live `ada-ws` path implemented but NOT exercised: ada-dev :8005 is
  loopback on idc03; activation requires `ADA_REVIEW_ALLOW_LIVE=1` +
  review per card spec (litellm numbers measure a model with the
  Ada-reviewer prompt, not the live assistant).
- Corpus is n=8 smoke size; powered study + human spot-check needed
  before any activation decision. Human approval for risky work is
  preserved — reviews are evidence only.

## Verify

```
python3 -m pytest tests/devnest/test_ada_result_review.py -x -q   # 8 pass
python3 scripts/devnest/ada_result_review.py eval --backend replay
python3 scripts/devnest/ada_result_review.py eval --backend litellm --model chat
```

lessons:
- LiteLLM `LITELLM_URL` in litellm-chaba.env already ends in `/v1` — appending `/v1/chat/completions` 404s; normalize the base.
- `gemini-*-free` aliases can hang past 120s under quota pressure; `gemini-3.5-flash-lite` (paid alias) answered in ~2.5s.
- Reviewer models emit evidence refs like `checks["key with space"]` — resolvers must handle bracket-quoted keys, and max_tokens 3000 truncates JSON mid-object on `chat`.
- cd-relative `../../` path math inside run dirs created a stray `evals/evals/` tree — use repo-root-absolute paths in generators.
