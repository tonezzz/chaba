# bench-edu-manage — 2026-10-23

Card: edu-agent-benchmark. Three education-managing lanes on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

Turn 2 (card edu-agent-lane-lift-turn2): the agent loop gained structured-output hardening — `parallel_tool_calls:false`, `arguments` repair (balanced-brace / trailing-comma / literal_eval), schema-required validation with in-loop re-emit instead of silent `{}` execution, and a one-shot `response_format:json_object` escalation when a reply looks like a malformed text-blob call (auto-disabled lane-wide on backend 4xx).

| lane | capture F1 | P / R | dedupe | sched/ops | recall | draft-Q (judge) | completed | p50 lat | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| local-gpt-oss-20b | 1.0 | 1.0 / 1.0 | 3/5 | 5/5 | 3/3 | n/a (n=0) | 13/13 | 78.3s | 43305/6191 |

## vs 2026-10-22 baseline (identical fixture, same harness pre-change)

| lane | capture F1 | dedupe | sched/ops | recall | draft-Q | completed | p50 lat |
|---|---|---|---|---|---|---|---|
| current (baseline) | 1.0 | 3/5 | 5/5 | 3/3 | 5.0 | 13/13 | ~0-3s |
| clawbot (baseline) | 1.0 | 4/5 | 5/5 | 3/3 | 4.72 | 13/13 | 12.5s |
| hermes3:8b (baseline) | 0.545 | 2/5 | 3/5 | 1/3 | 3.9 | 12/13 | 19.4s |
| **local-gpt-oss-20b (turn 2)** | **1.0** | **3/5** | **5/5** | **3/3** | n/a | **13/13** | 78.3s |

gpt-oss:20b is the first LOCAL lane to match `current`/`clawbot` on capture, ops and recall — a clean sweep over hermes3:8b (F1 0.545→1.0, ops 3/5→5/5, recall 1/3→3/3, completions 12/13→13/13). Its two dedupe misses are the same systemic blind spots already measured: t3 re-ask created 'tailscale ACL tags' instead of updating 'tailscale acl basics', and t6 filed 'ada nest heartbeat escalation' without the `ada-nest-*` family prefix + hub refresh. Cost: ~6x clawbot's p50 (78.3s vs 12.5s — 20.9B MXFP4 partially RAM-offloaded on the shared omen GPU) but ~42% fewer prompt tokens (43k vs 74k) and $0.

## Per-task

### local-gpt-oss-20b
- `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=114s filed: TCP BBR vs CUBIC difference(new)
- `t2-skip-commands` completed=True calls=1 llm=2 lat=20s
- `t3-update-tailscale` completed=True calls=2 llm=3 lat=78s filed: tailscale ACL tags(new)
- `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=134s filed: CAP theorem(new)
- `t5-thai-quantization` completed=True calls=4 llm=5 lat=144s filed: LLM quantization and GGUF(new)
- `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=78s filed: ada nest heartbeat escalation(new)
- `t7-ephemeral` completed=True calls=1 llm=2 lat=24s
- `o1-mark-learned` completed=True calls=3 llm=4 lat=96s filed: spaced repetition(upd)
- `o2-push-review` completed=True calls=3 llm=4 lat=119s filed: tailscale acl basics(upd)
- `o3-due-list` completed=True calls=1 llm=2 lat=42s
- `r1-recall-spaced` completed=True calls=1 llm=2 lat=27s
- `r2-recall-tailscale` completed=True calls=7 llm=8 lat=92s
- `r3-recall-none` completed=True calls=1 llm=2 lat=13s

## Method notes
- `current` = real pipeline path (mechanical filter -> flash-lite classify with the production CLASSIFY_PROMPT -> draft with DRAFT_PROMPT -> lesson-add upsert semantics incl. its meta-overwrite quirk). Ops/recall run the documented scripted-equivalent (deterministic).
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process on its declared provider.
- `local-gpt-oss-20b` = identical loop on omen ollama /v1 gpt-oss:20b (20.9B MXFP4, ~2.6GB VRAM + RAM offload — the shared-GPU guard held: lane ran sequential, no other model loaded; `--ollama-timeout` raised 150→300s because a ~9 tok/s reasoning model was hitting the old cap).
- `clawbot` lane NOT RUN this turn — mn01 has no `OPENROUTER_API_KEY` (secrets originate on macbook; never synced here) and no LiteLLM virtual key; direct OR call probes 401. Board request raised on the card for a key sync; lane skipped rather than fabricated.
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): local-gpt-oss-20b: arg_repairs=0 arg_errors=0 json_retries=0 json_mode=on. gpt-oss emitted spec-clean `tool_calls` all 13 tasks — the new machinery never fired. End-to-end correctness of all three paths was instead verified against a stubbed OpenAI-compat backend (repair→exec, reject→error feedback, blob→forced-JSON retry→exec; parallel_tool_calls=false on every request).
- Judge = one fixed model (gemini-3.5-flash-lite) for all lanes; it is also the `current` lane's model — symmetry caveat applies to draft-quality only. THIS RUN: judge unusable — both GEMINI_API_KEYs on mn01 (ada-ha-tony, ada-ha-michael) returned 429 on every attempt (free-tier daily quota) and no LiteLLM virtual key exists on this host, so draft-Q = n/a. All 7 filings keep full HTML in the result JSON (`tasks[].filings[].content`) — draft-Q is re-judgeable offline without rerunning the lane.
