# bench-edu-manage — 2026-10-23

Card: edu-agent-benchmark. Three education-managing lanes on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| local-gpt-oss-20b | 1.0 | 1.0 / 1.0 | 5/5 | 5/5 | 3/3 | n/a (n=0) | 13/13 | 81.6s | 36178/7327 |

## Per-task

### local-gpt-oss-20b
- `t1-create-bbr-cubic` completed=True calls=1 llm=2 lat=462s filed: TCP BBR vs CUBIC(new)
- `t2-skip-commands` completed=True calls=1 llm=2 lat=22s
- `t3-update-tailscale` completed=True calls=2 llm=3 lat=268s filed: tailscale acl basics(upd)
- `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=112s filed: CAP theorem in distributed systems(new)
- `t5-thai-quantization` completed=True calls=1 llm=2 lat=101s filed: LLM quantization(new)
- `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=82s filed: ada-nest-heartbeat-escalation(new)
- `t7-ephemeral` completed=True calls=1 llm=2 lat=53s
- `o1-mark-learned` completed=True calls=3 llm=4 lat=98s filed: spaced repetition(upd)
- `o2-push-review` completed=True calls=3 llm=4 lat=82s filed: tailscale acl basics(upd)
- `o3-due-list` completed=True calls=1 llm=2 lat=52s
- `r1-recall-spaced` completed=True calls=1 llm=2 lat=32s
- `r2-recall-tailscale` completed=True calls=2 llm=3 lat=38s
- `r3-recall-none` completed=True calls=1 llm=2 lat=14s

## Turn-3 store-awareness

This run used `--agent-topics`: each model call received the mock store's current topic titles. Against the prior gpt-oss run without that context (dedupe 3/5, ops 5/5, recall 3/3), this run scored dedupe 5/5, ops 5/5, recall 3/3. The prior run is a single-run comparison, not a controlled multi-rep result; draft quality was not judged (`--no-judge`). The prompt change is causal to the test configuration, but the size and generality of the lift still need repeats and a larger corpus.

## Method notes
- `current` = real pipeline path (mechanical filter -> flash-lite classify with the production CLASSIFY_PROMPT -> draft with DRAFT_PROMPT -> lesson-add upsert semantics incl. its meta-overwrite quirk). Ops/recall run the documented scripted-equivalent (deterministic).
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process on its declared provider.
- `local-gpt-oss-20b` = identical loop on omen ollama /v1 gpt-oss:20b.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): local-gpt-oss-20b: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=on
- Judge = one fixed model (gemini-3.5-flash-lite) for all lanes; it is also the `current` lane's model — symmetry caveat applies to draft-quality only.
