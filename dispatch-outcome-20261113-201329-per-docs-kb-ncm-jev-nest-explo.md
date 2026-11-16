# Dispatch outcome — ncm-jev-p0-replay-contract (2026-11-13)

## Task

P0 of `docs/kb/ncm-jev-nest-exploration-procedure.md`: freeze corpus,
implement the common worker contract, replay all arms, gate on
deterministic schema validity + provider-free replay, publish the
standard packet. No GPU/paid compute; NCM/JEV outputs never mint
permissions.

## What was built

`experiments/ncm-jev-p0/` — stdlib-only python3 harness
(`p0harness/`, CLI `python3 -m p0harness freeze|run|replay|packet|all`):

- **Frozen corpus** `corpus/frozen.json`: 10 tasks — 4 seeded Sudoku
  (pure-python port of `ncmthai.sudoku_data`, 40 clues), 3 Thai
  continuation fixtures, 3 fixed short prompts — plus a 24-line authored
  Thai training corpus and 60 recorded local-Ollama outputs
  (3 LLM arms × 10 tasks × seeds {42,7}). Frozen before running.
- **Worker contract v1**: every row carries the spec'd fields
  (task_id, input, candidate, model_id, model_revision, prompt_hash,
  seed, output, latency_ms, tokens_in, tokens_out, verdict,
  artifact_ref) + namespaced `meta`.
- **8 arms**: `ar_char_ngram` (real order-3 char AR on frozen corpus),
  `ncm_2level` (labeled contract stand-in — trained NCM stays blocked
  pending P1 authorized GPU), `llm_qwen3_0p6b` / `llm_llama32_1b` /
  `llm_qwen3_4b` (pinned by ollama sha256 digest + GGUF quant +
  hardware + decode; recorded once at freeze, replayed provider-free),
  `jev_route` (deterministic rules router, scored as a decision),
  `jev_routed` (route + selected pool candidate),
  `parallel_verified` (bounded pool + deterministic verifier/ranker).
- **Pins** in `manifest.json`: model/revision/tokenizer/quantization/
  hardware/decode per arm; corpus sha256; identity-field list for
  replay (latency_ms wall-clock-exempt).
- **Authority guard**: any output containing allowed_paths/tools/
  credentials/etc. is escalated + counted. 0 violations.
- **Verifier**: deterministic per-kind scoring on the claimed answer
  (last non-empty line / last grid): sudoku wellformed/valid/
  clues-preserved/solved, Thai ratio + degenerate guard, prompt checks,
  decision-schema check.
- **Packet** `packet/`: manifest.json, results.json (150 rows +
  summary), report.md, verdict.json (watch), education.html,
  replay-check.json, artifacts/.

## Result

P0 gate **PASS**: 150 rows, 0 schema errors, replay `ok=true` (0
identity mismatches, 0 provider calls), 0 guard violations.
Provisional signal only: qwen3:0.6b 12/20, llama3.2:1b 10/20,
qwen3:4b 4/20 (verbose reasoning needed a pinned larger num_predict
and still truncates on Thai cells), sim arms 7/20, jev_route 10/10
wellformed, jev_routed 10/20, parallel_verified 12/20. No arm solved a
Sudoku. Verdict: **watch** — contract proven, no quality claims; P1 GPU
stays blocked per the resource guard.

## Also

- Job report: `docs/ssot/jobs/experiments/2026-11-13-ncm-jev-p0-replay-contract.yml`
  (SSOT hooks validated).
- Commit `1b105515be` on `dispatch/20261113-201329-per-docs-kb-ncm-jev-nest-explo`;
  not pushed.
- qwen3:4b freeze needed `--only-arm` re-record + 300s timeout
  (verbose reasoning at ~7 tok/s).

## How to verify

```bash
cd experiments/ncm-jev-p0
python3 -m p0harness replay   # provider-free; exit 0 = gate pass
cat packet/report.md packet/verdict.json
```
