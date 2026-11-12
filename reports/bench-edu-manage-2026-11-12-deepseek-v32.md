# bench-edu-manage — 2026-11-12

Card: edu-agent-benchmark. 1 education-manager lane(s) on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| clawbot | 1.0 | 1.0 / 1.0 | 5/5 | 5/5 | 3/3 | 4.67 (n=8) | 13/13 | 11.1s | 74191/6049 |

## Per-task

### clawbot
- rep=1 `t1-create-bbr-cubic` completed=True calls=4 llm=4 lat=23s filed: TCP BBR vs CUBIC congestion control(new)
- rep=1 `t2-skip-commands` completed=True calls=1 llm=2 lat=4s
- rep=1 `t3-update-tailscale` completed=True calls=3 llm=4 lat=17s filed: tailscale acl basics(upd)
- rep=1 `t4-mixed-cap-private` completed=True calls=3 llm=3 lat=17s filed: CAP theorem in distributed systems(new)
- rep=1 `t5-thai-quantization` completed=True calls=3 llm=3 lat=25s filed: LLM Quantization and GGUF Speed(new)
- rep=1 `t6-hub-ada-nest-heartbeat` completed=True calls=5 llm=6 lat=40s filed: ada-nest-heartbeat-escalation(new), ada-nest-map(upd)
- rep=1 `t7-ephemeral` completed=True calls=5 llm=6 lat=22s
- rep=1 `o1-mark-learned` completed=True calls=3 llm=3 lat=9s filed: spaced repetition(upd)
- rep=1 `o2-push-review` completed=True calls=2 llm=3 lat=9s filed: tailscale acl basics(upd)
- rep=1 `o3-due-list` completed=True calls=1 llm=2 lat=5s
- rep=1 `r1-recall-spaced` completed=True calls=3 llm=3 lat=7s
- rep=1 `r2-recall-tailscale` completed=True calls=3 llm=3 lat=5s
- rep=1 `r3-recall-none` completed=True calls=3 llm=4 lat=11s

## Method notes
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `deepseek/deepseek-v3.2`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): clawbot: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=on
- Judge = gemini-3.5-flash-lite.
