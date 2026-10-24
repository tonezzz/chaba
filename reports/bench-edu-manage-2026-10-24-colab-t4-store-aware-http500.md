# bench-edu-manage — 2026-10-24

Card: edu-agent-benchmark. Three education-managing lanes on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

## Run disposition

This store-aware T4 attempt is partial, not a clean capability repetition: `t1-create-bbr-cubic` failed with HTTP 500 before any model/tool call, leaving 12/13 tasks complete. Keep it as an availability/runtime failure record; do not pool its capture F1 or dedupe score with completed repetitions. The other 12 tasks completed and ops/recall scored 5/5 and 3/3. No judge ran.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| local-gpt-oss-20b | 0.889 | 1.0 / 0.8 | 3/5 | 5/5 | 3/3 | n/a (n=0) | 12/13 | 16.1s | 36414/6162 |

## Per-task

### local-gpt-oss-20b
- `t1-create-bbr-cubic` completed=False calls=0 llm=0 lat=34s ERR=HTTP 500
- `t2-skip-commands` completed=True calls=1 llm=2 lat=272s
- `t3-update-tailscale` completed=True calls=3 llm=4 lat=47s filed: tailscale acl basics(upd)
- `t4-mixed-cap-private` completed=True calls=1 llm=2 lat=22s filed: CAP theorem in distributed systems(new)
- `t5-thai-quantization` completed=True calls=1 llm=2 lat=17s filed: LLM quantization(new)
- `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=13s filed: ada nest heartbeat escalation(new)
- `t7-ephemeral` completed=True calls=3 llm=4 lat=16s
- `o1-mark-learned` completed=True calls=3 llm=4 lat=16s filed: spaced repetition(upd)
- `o2-push-review` completed=True calls=3 llm=4 lat=16s filed: tailscale acl basics(upd)
- `o3-due-list` completed=True calls=1 llm=2 lat=9s
- `r1-recall-spaced` completed=True calls=1 llm=2 lat=5s
- `r2-recall-tailscale` completed=True calls=1 llm=2 lat=6s
- `r3-recall-none` completed=True calls=1 llm=2 lat=2s

## Method notes
- `current` = real pipeline path (mechanical filter -> flash-lite classify with the production CLASSIFY_PROMPT -> draft with DRAFT_PROMPT -> lesson-add upsert semantics incl. its meta-overwrite quirk). Ops/recall run the documented scripted-equivalent (deterministic).
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process on its declared provider.
- `local-gpt-oss-20b` = identical loop on omen ollama /v1 gpt-oss:20b.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): local-gpt-oss-20b: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=on
- Judge = one fixed model (gemini-3.5-flash-lite) for all lanes; it is also the `current` lane's model — symmetry caveat applies to draft-quality only.
