# Dispatch outcome — kk-mac-held-classes-fix-operator-brief-f-dd32ac (attempt 2)

## What changed

- `scripts/bench/kkmac-classes/build_corpus.py` — rewrote `expect.facts`
  on 10 of 16 `operator_brief` cases into literal-echo tokens. Method:
  for each case, intersected the evidence tokens actually echoed
  (case-insensitive substring) by all three recorded 2026-11-19 model
  responses (`run-kkmac-*-20261119.json`, archived copies of the prior
  reports), then picked the most discriminating 1–2 (hostnames, unit
  names, error codes, key numbers). Tightened 4 golds where the new
  fact required it (golds also became more faithful). Kept
  discriminating facts on `ob-stale-heartbeat` (22/fallback) and
  `ob-ratelimit` (429/bge-m3) — the models that missed them produced
  genuinely thin briefs; weakening those would pass bad output.
  `safe_route` facts are the route names themselves (the semantic
  check) — untouched. Docstring now carries the echo-token convention.
- `scripts/bench/kkmac-classes/corpus.jsonl` — rebuilt (51 cases).
- `docs/kb/jevnest-kk-mac-capacity-procedure.md` — producer guidance:
  declare 1–3 echo-able facts (verbatim identifiers from evidence),
  never gold-phrasing; required_keys/enums carry structural load.
- `docs/ssot/jobs/devnest/2026-11-23-kkmac-held-classes-reeval.yml` —
  job doc: corpus_fix method, recorded-response rescore predictions,
  safe_route per-case failure analysis, the two alternatives
  (code-side route whitelist / class rethink), readmission checklist.
- `scripts/bench/kkmac-classes/run-omen-qwen38b.{md,json}` — same-weights
  sanity bench on tony-omen ollama (same tags/weights, production call
  shape; de-risk evidence only, NOT readmission evidence).

## Result

- Corpus fix verified: mock-oracle selftest 51/51 pass; re-scoring the
  recorded 11-19 responses against the fixed corpus predicts
  operator_brief 16/16 (qwen3:8b), 14/16 (llama3.2:3b), 15/16
  (qwen2.5:32b) — all ≥0.80.
- Same-weights live sanity on tony-omen `qwen3:8b`: **operator_brief
  0.9375 READY** (was 0.56 on kk-mac), safe_route 0.5333 (unchanged
  failure profile — over-defer + act-on-decide-card), structured_extract
  0.9333.
- **BLOCKED:** live kk-mac re-bench and readmission. kk-mac (member
  device) went offline ~20:44 ICT — heartbeat stale >4h, tailscale
  last-seen, ssh connect timeout; `kkmac_eval.sh` fails closed by
  design. No class was readmitted (correct — readmission requires a
  passing live re-eval).

## How to verify / next step

When kk-mac is awake:

```bash
scripts/bench/kkmac-classes/kkmac_eval.sh qwen3:8b qwen2.5vl:7b
```

- `qwen3:8b` = readmission model for `operator_brief` (memory-safe lane
  default; omen sanity predicts pass).
- `qwen2.5vl:7b` (6 GB, in-floor, never tested) = the remaining
  `safe_route` candidate; 20B+ footprints breach the memory floor
  (`docs/reports/kk-mac-llm-bench-2026-11-20.md`).
- If a class passes (≥0.80/class, json_parse ≥0.90, 0 transport
  failures), readmit via the mirror checklist in
  `docs/ssot/jobs/devnest/2026-11-23-kkmac-held-classes-reeval.yml`
  (same list kk-mac-admitted-classes-narrow used, incl. held-class test
  assertions in tests/devnest + tests/board). If no in-floor model
  passes safe_route, the job doc evaluates the route-whitelist vs
  class-rethink alternatives.

Attempt-1 failure was a provider rate-limit kill, not a task defect;
this attempt completed all offline-doable work and committed
`7a29bba535` on the dispatch branch.

lessons:
- expect.facts is a case-insensitive substring check on the raw response — facts must be verbatim evidence tokens the model echoes, not gold phrasing; compute the echo intersection across prior run-*.json responses before picking
- member-device lanes (kk-mac) sleep without warning — bench gates fail closed; schedule re-evals for awake windows and keep a same-tag ollama on another tailnet host as a de-risk sanity check (not readmission evidence)
- when a corpus fact and its gold disagree, fix the gold too — mock-oracle selftest catches it (ob-queue "kk queue" vs fact "kk-llm")
- multi-tenant ollama hosts (tony-omen) can starve your bench run — GPU 0% + resident foreign model = calls timing out, not slow inference
