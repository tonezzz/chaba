# NCM + JEV + Nest — P0 replay contract benchmark

- procedure: `docs/kb/ncm-jev-nest-exploration-procedure.md#p0`
- corpus: `ncm-jev-p0-corpus` sha256 `e91f3d23ab3dbf43…`
- code revision: `091d708818337789280965f937830e46eb402650`
- seeds: [42, 7]
- rows: 150 contract rows over 10 tasks

## P0 gate

- schema validity: **PASS** (0 errors)
- reproducible replay from manifest.json without provider calls: **PASS** (150 rows, 0 mismatches)
- authority-guard violations: 0

## Arms

| arm | class | model_id | revision | quant | hw | sim |
| --- | --- | --- | --- | --- | --- | --- |
| ar_char_ngram | generative | ar-charngram3-local | `src-9541b730fa` | none | cpu-python3-stdlib | False |
| ncm_2level | generative | ncm-2level-standin | `src-9541b730fa` | none | cpu-python3-stdlib | True |
| llm_qwen3_0p6b | generative | qwen3:0.6b | `7df6b6e09427a7` | Q4_K_M | tony-omen ollama gguf (local) | False |
| llm_llama32_1b | generative | llama3.2:1b | `baf6a787fdffd6` | Q8_0 | tony-omen ollama gguf (local) | False |
| llm_qwen3_4b | generative | qwen3:4b | `359d7dd4bcdab3` | Q4_K_M | tony-omen ollama gguf (local) | False |
| jev_route | decision | jev-rules-v1 | `src-9541b730fa` | none | cpu-python3-stdlib | False |
| jev_routed | composite | jev-rules-v1+pool | `src-9541b730fa` | none | cpu+recorded | False |
| parallel_verified | composite | bounded-pool+det-verifier | `src-9541b730fa` | none | cpu+recorded | False |

## Results per arm

| candidate | n | pass | fail | escalate | mean score | tokens_out | mean latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ar_char_ngram | 20 | 7 | 13 | 0 | 0.41 | 1919 | 0.0 |
| jev_route | 10 | 10 | 0 | 0 | None | 50 | 0.0 |
| jev_routed | 20 | 10 | 10 | 0 | None | 3979 | 20781.5 |
| llm_llama32_1b | 20 | 10 | 10 | 0 | 0.58 | 1774 | 8397.0 |
| llm_qwen3_0p6b | 20 | 12 | 8 | 0 | 0.68 | 1043 | 1514.8 |
| llm_qwen3_4b | 20 | 4 | 16 | 0 | 0.455 | 13280 | 121471.2 |
| ncm_2level | 20 | 7 | 13 | 0 | 0.409 | 1917 | 1.2 |
| parallel_verified | 20 | 12 | 8 | 0 | None | 6653 | 9913.0 |

## Method

1. Corpus frozen before running (`corpus/frozen.json`): 4 seeded Sudoku puzzles (ncmthai token format), 3 Thai continuation fixtures, 3 fixed short prompts, and one recorded local-Ollama output per LLM arm × task × seed.
2. Every arm emits the worker-contract row (task_id,input,candidate,model_id,model_revision,prompt_hash,seed,output,latency_ms,tokens_in,tokens_out,verdict,artifact_ref).
3. Deterministic verifier scores each output — the claimed answer (last non-empty line / last grid), so reasoning prose doesn't count as the answer; the authority guard escalates any output containing permission-minting keys.
4. Replay regenerates all rows from manifest.json and compares identity fields (everything except wall-clock latency).

## Honest caveats

- `ncm_2level` is a contract stand-in, NOT the trained NCM — its scores measure the harness, not the paper architecture. Real NCM numbers require the P1 GPU stage, which stays blocked until authorized compute exists.
- LLM arms are small local GGUF models; their outputs are real inference but represent the smallest authorized tier.
- `ar_char_ngram` is a real (if weak) AR baseline trained on the 24-line frozen Thai corpus + task references.
- P0 answers 'does the contract/replay machinery work', not 'which generator is best'. Quality claims wait for P3.

## Verdict: **watch** (confidence: high)

- P0 gate: deterministic schema validity + reproducible replay from manifest.json without provider calls — PASS
- 150 rows replayed, 0 identity mismatches, 0 schema errors, 0 authority-guard violations
- ncm_2level arm is a deterministic contract stand-in; the trained NCM checkpoint stays blocked until P1 authorized GPU
- LLM arms used pinned local Ollama models recorded at freeze; replay needs no provider
