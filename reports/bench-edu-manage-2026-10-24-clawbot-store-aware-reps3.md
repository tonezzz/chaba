# bench-edu-manage — 2026-10-24

Card: edu-agent-benchmark. 1 education-manager lane(s) on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | reps | F1 mean [range] | dedupe mean [range] | ops mean [range] | recall mean [range] | complete | p50 mean [range] | avg tokens in/out; draft-Q |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clawbot | 3 | 1.00 [1.00-1.00] | 0.93 [0.80-1.00] | 1.00 [1.00-1.00] | 1.00 [1.00-1.00] | 39/39 | 14.20 [12.90-15.50]s | 58776/8827 (judge n/a) |

Ranges are across independent repetitions; completion is the combined count. Reps remain separate in the JSON.

## Per-repetition summary
| lane | rep | F1 | dedupe | ops | recall | completed | p50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| clawbot | 1 | 1.0 | 4/5 | 5/5 | 3/3 | 13/13 | 12.9s |
| clawbot | 2 | 1.0 | 5/5 | 5/5 | 3/3 | 13/13 | 15.5s |
| clawbot | 3 | 1.0 | 5/5 | 5/5 | 3/3 | 13/13 | 14.2s |

## Per-task

### clawbot
- rep=1 `t1-create-bbr-cubic` completed=True calls=3 llm=4 lat=89s filed: TCP BBR vs CUBIC congestion control(new)
- rep=1 `t2-skip-commands` completed=True calls=1 llm=2 lat=11s
- rep=1 `t3-update-tailscale` completed=True calls=4 llm=5 lat=14s filed: tailscale acl basics(upd)
- rep=1 `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=9s filed: CAP theorem in distributed systems(new)
- rep=1 `t5-thai-quantization` completed=True calls=3 llm=4 lat=23s filed: Ada quantization in LLM models(new)
- rep=1 `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=13s filed: Ada Nest heartbeat escalation process(new)
- rep=1 `t7-ephemeral` completed=True calls=1 llm=2 lat=19s
- rep=1 `o1-mark-learned` completed=True calls=2 llm=3 lat=4s filed: spaced repetition(upd)
- rep=1 `o2-push-review` completed=True calls=2 llm=3 lat=7s filed: tailscale acl basics(upd)
- rep=1 `o3-due-list` completed=True calls=1 llm=2 lat=15s
- rep=1 `r1-recall-spaced` completed=True calls=1 llm=2 lat=3s
- rep=1 `r2-recall-tailscale` completed=True calls=3 llm=4 lat=15s
- rep=1 `r3-recall-none` completed=True calls=2 llm=3 lat=6s
- rep=2 `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=13s filed: TCP BBR vs CUBIC congestion control(new)
- rep=2 `t2-skip-commands` completed=True calls=1 llm=2 lat=24s
- rep=2 `t3-update-tailscale` completed=True calls=3 llm=4 lat=21s filed: tailscale acl basics(upd)
- rep=2 `t4-mixed-cap-private` completed=True calls=4 llm=4 lat=19s filed: CAP theorem distributed systems(new)
- rep=2 `t5-thai-quantization` completed=True calls=4 llm=4 lat=22s filed: LLM quantization basics(new)
- rep=2 `t6-hub-ada-nest-heartbeat` completed=True calls=4 llm=4 lat=25s filed: ada-nest-heartbeat-escalation(new)
- rep=2 `t7-ephemeral` completed=True calls=3 llm=3 lat=6s
- rep=2 `o1-mark-learned` completed=True calls=2 llm=3 lat=22s filed: spaced repetition(upd)
- rep=2 `o2-push-review` completed=True calls=2 llm=3 lat=11s filed: tailscale acl basics(upd)
- rep=2 `o3-due-list` completed=True calls=1 llm=2 lat=6s
- rep=2 `r1-recall-spaced` completed=True calls=1 llm=2 lat=9s
- rep=2 `r2-recall-tailscale` completed=True calls=3 llm=3 lat=16s
- rep=2 `r3-recall-none` completed=True calls=1 llm=2 lat=4s
- rep=3 `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=38s filed: TCP BBR CUBIC congestion control(new)
- rep=3 `t2-skip-commands` completed=True calls=1 llm=2 lat=10s
- rep=3 `t3-update-tailscale` completed=True calls=3 llm=4 lat=20s filed: tailscale acl basics(upd)
- rep=3 `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=32s filed: CAP theorem distributed systems(new)
- rep=3 `t5-thai-quantization` completed=True calls=3 llm=3 lat=25s filed: LLM quantization and GGUF format(new)
- rep=3 `t6-hub-ada-nest-heartbeat` completed=True calls=6 llm=7 lat=20s filed: ada-nest heartbeat escalation(new)
- rep=3 `t7-ephemeral` completed=True calls=3 llm=3 lat=18s
- rep=3 `o1-mark-learned` completed=True calls=2 llm=3 lat=14s filed: spaced repetition(upd)
- rep=3 `o2-push-review` completed=True calls=2 llm=3 lat=7s filed: tailscale acl basics(upd)
- rep=3 `o3-due-list` completed=True calls=1 llm=2 lat=8s
- rep=3 `r1-recall-spaced` completed=True calls=1 llm=2 lat=4s
- rep=3 `r2-recall-tailscale` completed=True calls=3 llm=4 lat=8s
- rep=3 `r3-recall-none` completed=True calls=1 llm=2 lat=4s

## Method notes
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process.
- `clawbot` rep 1 returned model IDs: `cohere/north-mini-code:free`, `dots-studio/dots-3-note-preview:free`, `google/gemma-4-31b-it:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `poolside/laguna-s-2.1:free`, `poolside/laguna-xs-2.1:free`, `recursive/flint-v1.0:free`, `xingchen-agi/xing4.0-29b-a4b:free`
- `clawbot` rep 2 returned model IDs: `cohere/north-mini-code:free`, `dots-studio/dots-3-note-preview:free`, `google/gemma-4-31b-it:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `poolside/laguna-s-2.1:free`, `poolside/laguna-xs-2.1:free`, `recursive/flint-v1.0:free`
- `clawbot` rep 3 returned model IDs: `cohere/north-mini-code:free`, `dots-studio/dots-3-note-preview:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `poolside/laguna-s-2.1:free`, `poolside/laguna-xs-2.1:free`, `recursive/flint-v1.0:free`, `xingchen-agi/xing4.0-29b-a4b:free`
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): clawbot: rep1: repairs=0 errors=0 retries=0 | rep2: repairs=0 errors=0 retries=0 | rep3: repairs=0 errors=0 retries=0
- Draft quality was not judged; saved HTML filings can be scored offline.
