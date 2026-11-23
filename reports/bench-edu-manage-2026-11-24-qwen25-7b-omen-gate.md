# bench-edu-manage — 2026-11-24

Card: edu-agent-benchmark. 2 education-manager lane(s) on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| current | 1.0 | 1.0 / 1.0 | 3/5 | 5/5 | 3/3 | 5.0 (n=5) | 13/13 | 0.0s | 896/211 |
| clawbot | 0.75 | 1.0 / 0.6 | 3/5 | 2/5 | 1/3 | 4.27 (n=3) | 10/13 | 61.7s | 28851/1520 |

## Per-task

### current
- rep=1 `t1-create-bbr-cubic` completed=True calls=1 llm=2 lat=3s filed: TCP BBR Versus CUBIC Congestion Control(new)
- rep=1 `t2-skip-commands` completed=True calls=0 llm=0 lat=0s
- rep=1 `t3-update-tailscale` completed=True calls=1 llm=2 lat=2s filed: Understanding Tailscale ACLs and Device Tags(new)
- rep=1 `t4-mixed-cap-private` completed=True calls=1 llm=2 lat=3s filed: Understanding the CAP Theorem in Distributed Systems(new)
- rep=1 `t5-thai-quantization` completed=True calls=1 llm=2 lat=2s filed: LLM Quantization and GGUF Format Explained(new)
- rep=1 `t6-hub-ada-nest-heartbeat` completed=True calls=1 llm=2 lat=2s filed: Ada Nest Heartbeat Escalation and Paging Mechanics(new)
- rep=1 `t7-ephemeral` completed=True calls=0 llm=1 lat=1s
- rep=1 `o1-mark-learned` completed=True calls=1 llm=0 lat=0s
- rep=1 `o2-push-review` completed=True calls=1 llm=0 lat=0s
- rep=1 `o3-due-list` completed=True calls=1 llm=0 lat=0s
- rep=1 `r1-recall-spaced` completed=True calls=1 llm=0 lat=0s
- rep=1 `r2-recall-tailscale` completed=True calls=1 llm=0 lat=0s
- rep=1 `r3-recall-none` completed=True calls=0 llm=0 lat=0s

### clawbot
- rep=1 `t1-create-bbr-cubic` completed=True calls=2 llm=2 lat=284s filed: tcp-bbr-vs-cubic(new)
- rep=1 `t2-skip-commands` completed=True calls=0 llm=1 lat=22s
- rep=1 `t3-update-tailscale` completed=False calls=2 llm=1 lat=387s ERR=TimeoutError: timed out
- rep=1 `t4-mixed-cap-private` completed=False calls=2 llm=1 lat=335s ERR=TimeoutError: timed out
- rep=1 `t5-thai-quantization` completed=True calls=3 llm=3 lat=583s filed: ada-quantization(new)
- rep=1 `t6-hub-ada-nest-heartbeat` completed=True calls=3 llm=3 lat=280s filed: ada-nest-heartbeat-escalation(new)
- rep=1 `t7-ephemeral` completed=True calls=1 llm=2 lat=62s
- rep=1 `o1-mark-learned` completed=True calls=1 llm=2 lat=50s
- rep=1 `o2-push-review` completed=True calls=1 llm=2 lat=14s
- rep=1 `o3-due-list` completed=False calls=2 llm=3 lat=114s ERR=HTTP 400
- rep=1 `r1-recall-spaced` completed=True calls=1 llm=2 lat=28s
- rep=1 `r2-recall-tailscale` completed=True calls=1 llm=2 lat=47s
- rep=1 `r3-recall-none` completed=True calls=1 llm=2 lat=34s

## Method notes
- `current` = real pipeline path (mechanical filter -> flash-lite classify with the production CLASSIFY_PROMPT -> draft with DRAFT_PROMPT -> lesson-add upsert semantics incl. its meta-overwrite quirk). Ops/recall run the documented scripted-equivalent (deterministic).
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `qwen2.5:7b`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): current: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=off; clawbot: arg_repairs=0 arg_errors=0 json_retries=1 json_mode=on
- Judge = gemini-3.5-flash-lite. It is also the `current` lane's model; the symmetry caveat applies to draft-quality.
