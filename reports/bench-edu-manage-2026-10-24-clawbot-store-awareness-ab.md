# Clawbot store-awareness A/B — 2026-10-24

Same 13-task fixture and MockStore, three reps per condition, no judge.
The treatment run used `--agent-topics`; the baseline omitted it.

| condition | F1 mean | dedupe | ops | recall | completion | p50 mean |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0.926 | 11/15 | 15/15 | 8/9 | 38/39 | 10.7s |
| store-aware | 1.000 | 14/15 | 15/15 | 9/9 | 39/39 | 14.2s |

Per-rep values:

| condition | rep | F1 | dedupe | ops | recall | complete | p50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 1 | 0.889 | 4/5 | 5/5 | 3/3 | 13/13 | 11.9s |
| baseline | 2 | 0.889 | 4/5 | 5/5 | 3/3 | 12/13 | 11.8s |
| baseline | 3 | 1.000 | 3/5 | 5/5 | 2/3 | 13/13 | 8.4s |
| store-aware | 1 | 1.000 | 4/5 | 5/5 | 3/3 | 13/13 | 12.9s |
| store-aware | 2 | 1.000 | 5/5 | 5/5 | 3/3 | 13/13 | 15.5s |
| store-aware | 3 | 1.000 | 5/5 | 5/5 | 3/3 | 13/13 | 14.2s |

Interpretation: store-aware runs complete all tasks and dedupe 14/15,
vs baseline 11/15; encouraging but not causal proof. `openrouter/free`
rotated across 8-12 model IDs per rep, conditions ran store-aware first
then baseline, and baseline rep 2 had an HTTP 400 on the family/hub task.
Draft quality was not judged. The input-token means were 58.8k with
topic context and 63.1k without, but provider/model mix and call count
also vary. Raw reports preserve per-task calls, returned model IDs and
filing HTML:

- `reports/bench-edu-manage-2026-10-24-clawbot-baseline-reps3.{json,md}`
- `reports/bench-edu-manage-2026-10-24-clawbot-store-aware-reps3.{json,md}`

Next: pin `nvidia/nemotron-3.5-super-vl:free` with `--or-model` and run
the two conditions at least three reps each in alternating order.
