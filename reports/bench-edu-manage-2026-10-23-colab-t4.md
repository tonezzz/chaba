# bench-edu-manage — 2026-10-23

Card: edu-agent-benchmark. Three education-managing lanes on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| local-gpt-oss-20b | 1.0 | 1.0 / 1.0 | 4/5 | 4/5 | 1/3 | n/a (n=0) | 13/13 | 14.7s | 41472/6921 |

## Per-task

### local-gpt-oss-20b
- `t1-create-bbr-cubic` completed=True calls=1 llm=2 lat=699s filed: TCP BBR vs CUBIC(new)
- `t2-skip-commands` completed=True calls=1 llm=2 lat=5s
- `t3-update-tailscale` completed=True calls=2 llm=3 lat=34s filed: tailscale acl basics(upd)
- `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=15s filed: CAP theorem(new)
- `t5-thai-quantization` completed=True calls=3 llm=4 lat=28s filed: Ada quantization in LLM(new)
- `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=15s filed: ada nest heartbeat escalation(new)
- `t7-ephemeral` completed=True calls=1 llm=2 lat=7s
- `o1-mark-learned` completed=True calls=3 llm=4 lat=16s filed: spaced repetition(upd)
- `o2-push-review` completed=True calls=3 llm=4 lat=13s filed: tailscale acl basics(upd)
- `o3-due-list` completed=True calls=1 llm=2 lat=7s
- `r1-recall-spaced` completed=True calls=3 llm=4 lat=9s
- `r2-recall-tailscale` completed=True calls=4 llm=5 lat=8s
- `r3-recall-none` completed=True calls=2 llm=3 lat=23s filed: quantum annealing(new)

## Method notes
- `current` = real pipeline path (mechanical filter -> flash-lite classify with the production CLASSIFY_PROMPT -> draft with DRAFT_PROMPT -> lesson-add upsert semantics incl. its meta-overwrite quirk). Ops/recall run the documented scripted-equivalent (deterministic).
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process on its declared provider.
- `local-gpt-oss-20b` = identical loop on omen ollama /v1 gpt-oss:20b.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): local-gpt-oss-20b: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=on
- Judge = one fixed model (gemini-3.5-flash-lite) for all lanes; it is also the `current` lane's model — symmetry caveat applies to draft-quality only.
