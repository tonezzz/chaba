# bench-edu-manage — 2026-10-24

Card: edu-agent-benchmark. 1 education-manager lane(s) on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | reps | F1 mean [range] | dedupe mean [range] | ops mean [range] | recall mean [range] | complete | p50 mean [range] | avg tokens in/out; draft-Q |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clawbot | 3 | 0.93 [0.89-1.00] | 0.73 [0.60-0.80] | 1.00 [1.00-1.00] | 0.89 [0.67-1.00] | 38/39 | 10.70 [8.40-11.90]s | 63056/9092 (judge n/a) |

Ranges are across independent repetitions; completion is the combined count. Reps remain separate in the JSON.

## Per-repetition summary
| lane | rep | F1 | dedupe | ops | recall | completed | p50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| clawbot | 1 | 0.889 | 4/5 | 5/5 | 3/3 | 13/13 | 11.9s |
| clawbot | 2 | 0.889 | 4/5 | 5/5 | 3/3 | 12/13 | 11.8s |
| clawbot | 3 | 1.0 | 3/5 | 5/5 | 2/3 | 13/13 | 8.4s |

## Per-task

### clawbot
- rep=1 `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=32s filed: TCP BBR vs CUBIC congestion control(new)
- rep=1 `t2-skip-commands` completed=True calls=0 llm=1 lat=1s
- rep=1 `t3-update-tailscale` completed=True calls=3 llm=4 lat=15s filed: tailscale acl basics(upd)
- rep=1 `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=20s filed: CAP theorem distributed systems(new)
- rep=1 `t5-thai-quantization` completed=True calls=2 llm=3 lat=12s filed: LLM quantization GGUF(new)
- rep=1 `t6-hub-ada-nest-heartbeat` completed=True calls=4 llm=5 lat=20s filed: ada-nest-map(upd)
- rep=1 `t7-ephemeral` completed=True calls=1 llm=2 lat=9s
- rep=1 `o1-mark-learned` completed=True calls=2 llm=3 lat=13s filed: spaced repetition(upd)
- rep=1 `o2-push-review` completed=True calls=2 llm=3 lat=6s filed: tailscale acl basics(upd)
- rep=1 `o3-due-list` completed=True calls=1 llm=2 lat=8s
- rep=1 `r1-recall-spaced` completed=True calls=2 llm=3 lat=21s
- rep=1 `r2-recall-tailscale` completed=True calls=5 llm=4 lat=12s
- rep=1 `r3-recall-none` completed=True calls=4 llm=5 lat=8s
- rep=2 `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=12s filed: TCP BBR vs CUBIC congestion control(new)
- rep=2 `t2-skip-commands` completed=True calls=2 llm=3 lat=17s
- rep=2 `t3-update-tailscale` completed=True calls=3 llm=4 lat=11s filed: tailscale acl basics(upd)
- rep=2 `t4-mixed-cap-private` completed=True calls=8 llm=9 lat=35s filed: CAP theorem distributed systems(new)
- rep=2 `t5-thai-quantization` completed=True calls=2 llm=3 lat=22s filed: Quantization in LLM models(new)
- rep=2 `t6-hub-ada-nest-heartbeat` completed=False calls=4 llm=4 lat=13s ERR=HTTP 400
- rep=2 `t7-ephemeral` completed=True calls=1 llm=2 lat=13s
- rep=2 `o1-mark-learned` completed=True calls=2 llm=3 lat=8s filed: spaced repetition(upd)
- rep=2 `o2-push-review` completed=True calls=2 llm=3 lat=6s filed: tailscale acl basics(upd)
- rep=2 `o3-due-list` completed=True calls=1 llm=2 lat=21s
- rep=2 `r1-recall-spaced` completed=True calls=6 llm=7 lat=12s
- rep=2 `r2-recall-tailscale` completed=True calls=3 llm=4 lat=10s
- rep=2 `r3-recall-none` completed=True calls=3 llm=4 lat=11s
- rep=3 `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=10s filed: TCP BBR vs CUBIC congestion control(new)
- rep=3 `t2-skip-commands` completed=True calls=1 llm=2 lat=5s
- rep=3 `t3-update-tailscale` completed=True calls=2 llm=3 lat=8s filed: tailscale-acls(new)
- rep=3 `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=23s filed: CAP theorem in distributed systems(new)
- rep=3 `t5-thai-quantization` completed=True calls=3 llm=3 lat=21s filed: LLM model quantization(new)
- rep=3 `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=13s filed: ada nest heartbeat escalation(new)
- rep=3 `t7-ephemeral` completed=True calls=3 llm=3 lat=15s
- rep=3 `o1-mark-learned` completed=True calls=2 llm=3 lat=4s filed: spaced repetition(upd)
- rep=3 `o2-push-review` completed=True calls=2 llm=3 lat=7s filed: tailscale acl basics(upd)
- rep=3 `o3-due-list` completed=True calls=1 llm=2 lat=5s
- rep=3 `r1-recall-spaced` completed=True calls=1 llm=2 lat=5s
- rep=3 `r2-recall-tailscale` completed=True calls=5 llm=5 lat=20s
- rep=3 `r3-recall-none` completed=True calls=3 llm=3 lat=4s

## Method notes
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `openrouter/free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process.
- `clawbot` rep 1 returned model IDs: `cohere/north-mini-code:free`, `dots-studio/dots-3-note-preview:free`, `google/gemma-4-26b-a4b-it:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `poolside/laguna-xs-2.1:free`, `recursive/flint-v1.0:free`
- `clawbot` rep 2 returned model IDs: `cohere/north-mini-code:free`, `dots-studio/dots-3-note-preview:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `poolside/laguna-s-2.1:free`, `recursive/flint-v1.0:free`
- `clawbot` rep 3 returned model IDs: `cohere/north-mini-code:free`, `dots-studio/dots-3-note-preview:free`, `liquid/lfm-2.5-2.6b:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `poolside/laguna-s-2.1:free`, `poolside/laguna-xs-2.1:free`, `recursive/flint-v1.0:free`, `xingchen-agi/xing4.0-29b-a4b:free`
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): clawbot: rep1: repairs=0 errors=0 retries=0 | rep2: repairs=0 errors=1 retries=0 | rep3: repairs=0 errors=0 retries=0
- Draft quality was not judged; saved HTML filings can be scored offline.
