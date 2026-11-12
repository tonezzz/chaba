# bench-edu-manage — 2026-11-12

Card: edu-agent-benchmark. 1 education-manager lane(s) on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| local-qwen3-8b | 1.0 | 1.0 / 1.0 | 4/5 | 5/5 | 1/3 | 4.45 (n=8) | 13/13 | 17.9s | 42774/14363 |

## Per-task

### local-qwen3-8b
- rep=1 `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=24s filed: TCP BBR vs CUBIC Congestion Control(new)
- rep=1 `t2-skip-commands` completed=True calls=1 llm=2 lat=10s
- rep=1 `t3-update-tailscale` completed=True calls=3 llm=4 lat=45s filed: tailscale acl basics(upd)
- rep=1 `t4-mixed-cap-private` completed=True calls=3 llm=3 lat=26s filed: CAP Theorem in Distributed Systems(new)
- rep=1 `t5-thai-quantization` completed=True calls=2 llm=3 lat=33s filed: Quantization in LLM Models GGUF(new)
- rep=1 `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=18s filed: ada nest heartbeat escalation(new)
- rep=1 `t7-ephemeral` completed=True calls=3 llm=4 lat=21s
- rep=1 `o1-mark-learned` completed=True calls=2 llm=3 lat=26s filed: spaced repetition(upd)
- rep=1 `o2-push-review` completed=True calls=2 llm=3 lat=15s filed: tailscale acl basics(upd)
- rep=1 `o3-due-list` completed=True calls=1 llm=2 lat=11s
- rep=1 `r1-recall-spaced` completed=True calls=1 llm=2 lat=10s
- rep=1 `r2-recall-tailscale` completed=True calls=1 llm=2 lat=11s
- rep=1 `r3-recall-none` completed=True calls=2 llm=3 lat=14s filed: quantum annealing(new)

## Method notes
- `local-qwen3-8b` = identical loop on http://100.108.217.17:11434/v1 qwen3:8b.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): local-qwen3-8b: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=on
- Judge = gemini-3.5-flash-lite.
