# bench-edu-manage — 2026-10-23

Card: edu-agent-benchmark. Three education-managing lanes on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

## Turn-3 store-aware Colab repetition

This run used `--agent-topics` on the same gpt-oss:20b hardened loop and fixture, with weights on the Colab T4. It completed 13/13: F1 1.0, dedupe 5/5, ops 5/5, recall 3/3, p50 21.5s. Draft quality was not judged. The first task took 416s while the model loaded; steady-state tasks were much faster.

Compared with the earlier T4 run without topic context (dedupe 4/5, ops 4/5, recall 1/3, p50 14.7s), this is directionally consistent with a dedupe lift but not a controlled multi-rep estimate. The result is a separate one-rep run; do not infer that store-awareness caused the ops/recall changes.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| local-gpt-oss-20b | 1.0 | 1.0 / 1.0 | 5/5 | 5/5 | 3/3 | n/a (n=0) | 13/13 | 21.5s | 33905/7384 |

## Per-task

### local-gpt-oss-20b
- `t1-create-bbr-cubic` completed=True calls=1 llm=2 lat=416s filed: TCP BBR vs CUBIC(new)
- `t2-skip-commands` completed=True calls=1 llm=2 lat=5s
- `t3-update-tailscale` completed=True calls=2 llm=3 lat=43s filed: tailscale acl basics(upd)
- `t4-mixed-cap-private` completed=True calls=1 llm=2 lat=29s filed: CAP theorem in distributed systems(new)
- `t5-thai-quantization` completed=True calls=1 llm=2 lat=33s filed: LLM quantization and GGUF(new)
- `t6-hub-ada-nest-heartbeat` completed=True calls=1 llm=2 lat=40s filed: ada-nest-heartbeat-escalation(new)
- `t7-ephemeral` completed=True calls=1 llm=2 lat=13s
- `o1-mark-learned` completed=True calls=3 llm=4 lat=21s filed: spaced repetition(upd)
- `o2-push-review` completed=True calls=3 llm=4 lat=26s filed: tailscale acl basics(upd)
- `o3-due-list` completed=True calls=1 llm=2 lat=16s
- `r1-recall-spaced` completed=True calls=1 llm=2 lat=10s
- `r2-recall-tailscale` completed=True calls=2 llm=3 lat=8s
- `r3-recall-none` completed=True calls=1 llm=2 lat=2s

## Method notes
- `current` = real pipeline path (mechanical filter -> flash-lite classify with the production CLASSIFY_PROMPT -> draft with DRAFT_PROMPT -> lesson-add upsert semantics incl. its meta-overwrite quirk). Ops/recall run the documented scripted-equivalent (deterministic).
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process on its declared provider.
- `local-gpt-oss-20b` = identical loop on omen ollama /v1 gpt-oss:20b.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): local-gpt-oss-20b: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=on
- Judge = one fixed model (gemini-3.5-flash-lite) for all lanes; it is also the `current` lane's model — symmetry caveat applies to draft-quality only.
