# bench-edu-manage — 2026-10-22

Card: edu-agent-benchmark. Three education-managing lanes on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| current | 1.0 | 1.0 / 1.0 | 3/5 | 5/5 | 3/3 | 5.0 (n=5) | 13/13 | 0.0s | 890/211 |
| clawbot | 1.0 | 1.0 / 1.0 | 4/5 | 5/5 | 3/3 | 4.72 (n=8) | 13/13 | 12.5s | 74275/9350 |
| hermes | 0.545 | 0.5 / 0.6 | 2/5 | 3/5 | 1/3 | 3.9 (n=6) | 12/13 | 19.4s | 31126/3320 |

## Per-task

### current
- `t1-create-bbr-cubic` completed=True calls=1 llm=2 lat=3s filed: TCP BBR versus CUBIC congestion control(new)
- `t2-skip-commands` completed=True calls=0 llm=0 lat=0s
- `t3-update-tailscale` completed=True calls=1 llm=2 lat=3s filed: Tailscale ACLs and Device Tags(new)
- `t4-mixed-cap-private` completed=True calls=1 llm=2 lat=3s filed: Understanding the CAP Theorem in Distributed Systems(new)
- `t5-thai-quantization` completed=True calls=1 llm=2 lat=3s filed: LLM Quantization and GGUF Format Explained(new)
- `t6-hub-ada-nest-heartbeat` completed=True calls=1 llm=2 lat=3s filed: Ada Nest Heartbeat Escalation Mechanism(new)
- `t7-ephemeral` completed=True calls=0 llm=1 lat=1s
- `o1-mark-learned` completed=True calls=1 llm=0 lat=0s
- `o2-push-review` completed=True calls=1 llm=0 lat=0s
- `o3-due-list` completed=True calls=1 llm=0 lat=0s
- `r1-recall-spaced` completed=True calls=1 llm=0 lat=0s
- `r2-recall-tailscale` completed=True calls=1 llm=0 lat=0s
- `r3-recall-none` completed=True calls=0 llm=0 lat=0s

### clawbot
- `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=10s filed: TCP BBR vs CUBIC congestion control(new)
- `t2-skip-commands` completed=True calls=1 llm=2 lat=15s
- `t3-update-tailscale` completed=True calls=5 llm=6 lat=29s filed: tailscale tag vs acl rule(new)
- `t4-mixed-cap-private` completed=True calls=3 llm=3 lat=12s filed: CAP theorem distributed systems(new)
- `t5-thai-quantization` completed=True calls=3 llm=4 lat=29s filed: Quantization for LLM inference(new)
- `t6-hub-ada-nest-heartbeat` completed=True calls=7 llm=7 lat=31s filed: ada-nest-heartbeat-escalation(new), ada-nest-map(upd)
- `t7-ephemeral` completed=True calls=1 llm=2 lat=8s
- `o1-mark-learned` completed=True calls=2 llm=3 lat=4s filed: spaced repetition(upd)
- `o2-push-review` completed=True calls=2 llm=3 lat=14s filed: tailscale acl basics(upd)
- `o3-due-list` completed=True calls=1 llm=2 lat=6s
- `r1-recall-spaced` completed=True calls=4 llm=4 lat=14s
- `r2-recall-tailscale` completed=True calls=4 llm=5 lat=11s
- `r3-recall-none` completed=True calls=3 llm=4 lat=7s

### hermes
- `t1-create-bbr-cubic` completed=True calls=4 llm=3 lat=49s filed: TCP BBR vs CUBIC congestion control(new)
- `t2-skip-commands` completed=True calls=3 llm=2 lat=19s
- `t3-update-tailscale` completed=True calls=2 llm=2 lat=37s
- `t4-mixed-cap-private` completed=True calls=6 llm=4 lat=125s filed: CAP theorem in distributed systems(new)
- `t5-thai-quantization` completed=True calls=2 llm=2 lat=91s
- `t6-hub-ada-nest-heartbeat` completed=True calls=5 llm=3 lat=220s filed: ada nest heartbeat escalation(new)
- `t7-ephemeral` completed=False calls=11 llm=5 lat=659s filed: what time is it in Tokyo right now(new), is it going to rain this afternoon(new), Education(new) ERR=TimeoutError: timed out
- `o1-mark-learned` completed=True calls=1 llm=2 lat=10s
- `o2-push-review` completed=True calls=1 llm=2 lat=14s
- `o3-due-list` completed=True calls=1 llm=2 lat=13s
- `r1-recall-spaced` completed=True calls=1 llm=2 lat=14s
- `r2-recall-tailscale` completed=True calls=1 llm=2 lat=6s
- `r3-recall-none` completed=True calls=1 llm=2 lat=10s

## Method notes
- `current` = real pipeline path (mechanical filter -> flash-lite classify with the production CLASSIFY_PROMPT -> draft with DRAFT_PROMPT -> lesson-add upsert semantics incl. its meta-overwrite quirk). Ops/recall run the documented scripted-equivalent (deterministic).
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process on its declared provider.
- `hermes` = identical loop on omen ollama /v1 hermes3:8b.
- Judge = one fixed model (gemini-3.5-flash-lite) for all lanes; it is also the `current` lane's model — symmetry caveat applies to draft-quality only.
