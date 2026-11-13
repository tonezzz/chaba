# ncm-jev-p0 — contract & replay benchmark (no GPU)

P0 of `docs/kb/ncm-jev-nest-exploration-procedure.md`: freeze a corpus,
replay every task through every arm under a common worker contract, and
gate on deterministic schema validity + provider-free reproducible
replay. Stdlib-only (`python3`, no deps).

## Stages

```bash
cd experiments/ncm-jev-p0

python3 -m p0harness freeze   # ONCE: build corpus/frozen.json —
                              # seeded Sudoku (ncmthai token format),
                              # Thai fixtures, short prompts, and one
                              # recorded local-Ollama output per
                              # task/llm-arm/seed. Only stage that calls
                              # any model. --skip-llm / --only-arm ID
                              # supported.

python3 -m p0harness run      # packet/manifest.json + results.json +
                              # artifacts/ — zero provider calls

python3 -m p0harness replay   # P0 GATE: regenerate from manifest.json,
                              # compare identity fields, exit 0 on pass

python3 -m p0harness packet   # report.md + verdict.json + education.html
python3 -m p0harness all      # run + replay + packet
```

## Arms

| arm | what | pin |
| --- | --- | --- |
| `ar_char_ngram` | small Thai AR baseline — order-3 char model trained on the frozen corpus | code-hash revision, char-utf8, cpu |
| `ncm_2level` | **stand-in** two-level coarse→fine generator exercising the contract; NOT the trained NCM (checkpoint blocked until P1 authorized GPU) | code-hash revision, class6+char, cpu |
| `llm_qwen3_0p6b` / `llm_llama32_1b` / `llm_qwen3_4b` | pinned local Ollama models, recorded at freeze | ollama sha256 digest, GGUF quant from /api/tags, tony-omen hardware, `temperature:0` |
| `jev_route` | deterministic rules router, scored as a decision | jev-rules-v1 code hash |
| `jev_routed` | router → selected candidate from the pool | composite |
| `parallel_verified` | bounded pool → deterministic verifier/ranker → winner | pool pinned in manifest |

## Guarantees

- worker contract row: `task_id, input, candidate, model_id,
  model_revision, prompt_hash, seed, output, latency_ms, tokens_in,
  tokens_out, verdict, artifact_ref` (+ harness `meta`).
- replay gate compares all identity fields; `latency_ms` is recorded
  but wall-clock-exempt.
- authority guard: any output containing `allowed_paths`/`tools`/
  `credentials`/etc. is escalated and counted — models never mint
  permissions; Nest owns queueing/isolation.
- verdict `escalate` marks couldn't-run cells (e.g. provider down at
  freeze) — schema-valid, never counted as pass.
