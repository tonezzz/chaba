# bench-edu-manage — 2026-10-24

Card: edu-agent-benchmark. 1 education-manager lane(s) on one fixed corpus (`scripts/bench-edu-corpus.json`) against a LOCAL mock WP-lesson store — never prod WP.

| lane | reps | F1 mean [range] | dedupe mean [range] | ops mean [range] | recall mean [range] | complete | p50 mean [range] | avg tokens in/out; draft-Q |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| clawbot | 3 | 1.00 [1.00-1.00] | 0.60 [0.60-0.60] | 0.80 [0.60-1.00] | 1.00 [1.00-1.00] | 36/39 | 10.53 [9.40-12.50]s | 65021/8361 (judge n/a) |

Ranges are across independent repetitions; completion is the combined count. Reps remain separate in the JSON.

## Per-repetition summary
| lane | rep | F1 | dedupe | ops | recall | completed | p50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| clawbot | 1 | 1.0 | 3/5 | 4/5 | 3/3 | 12/13 | 9.7s |
| clawbot | 2 | 1.0 | 3/5 | 3/5 | 3/3 | 11/13 | 12.5s |
| clawbot | 3 | 1.0 | 3/5 | 5/5 | 3/3 | 13/13 | 9.4s |

## Per-task

### clawbot
- rep=1 `t1-create-bbr-cubic` completed=True calls=3 llm=3 lat=23s filed: TCP BBR vs CUBIC congestion control(new)
- rep=1 `t2-skip-commands` completed=True calls=1 llm=2 lat=7s
- rep=1 `t3-update-tailscale` completed=True calls=3 llm=3 lat=11s filed: Tailscale ACL tags vs rules(new)
- rep=1 `t4-mixed-cap-private` completed=True calls=3 llm=4 lat=8s filed: CAP theorem distributed systems(new)
- rep=1 `t5-thai-quantization` completed=True calls=3 llm=3 lat=12s filed: LLM quantization and GGUF format(new)
- rep=1 `t6-hub-ada-nest-heartbeat` completed=True calls=3 llm=3 lat=17s filed: ada nest heartbeat escalation(new)
- rep=1 `t7-ephemeral` completed=True calls=1 llm=2 lat=4s
- rep=1 `o1-mark-learned` completed=True calls=2 llm=3 lat=9s filed: spaced repetition(upd)
- rep=1 `o2-push-review` completed=True calls=2 llm=3 lat=5s filed: tailscale acl basics(upd)
- rep=1 `o3-due-list` completed=False calls=0 llm=1 lat=120s
- rep=1 `r1-recall-spaced` completed=True calls=6 llm=7 lat=7s
- rep=1 `r2-recall-tailscale` completed=True calls=5 llm=4 lat=10s
- rep=1 `r3-recall-none` completed=True calls=4 llm=5 lat=35s
- rep=2 `t1-create-bbr-cubic` completed=True calls=2 llm=3 lat=15s filed: TCP BBR vs CUBIC congestion control(new)
- rep=2 `t2-skip-commands` completed=True calls=1 llm=2 lat=8s
- rep=2 `t3-update-tailscale` completed=True calls=3 llm=3 lat=12s filed: Tailscale ACL tags vs rules(new)
- rep=2 `t4-mixed-cap-private` completed=True calls=3 llm=4 lat=8s filed: CAP theorem distributed systems(new)
- rep=2 `t5-thai-quantization` completed=True calls=3 llm=3 lat=45s filed: Ada LLM quantization GGUF(new)
- rep=2 `t6-hub-ada-nest-heartbeat` completed=True calls=3 llm=3 lat=10s filed: ada nest heartbeat escalation(new)
- rep=2 `t7-ephemeral` completed=True calls=1 llm=2 lat=4s
- rep=2 `o1-mark-learned` completed=True calls=2 llm=3 lat=3s filed: spaced repetition(upd)
- rep=2 `o2-push-review` completed=False calls=1 llm=2 lat=121s
- rep=2 `o3-due-list` completed=False calls=0 llm=1 lat=120s
- rep=2 `r1-recall-spaced` completed=True calls=4 llm=4 lat=8s
- rep=2 `r2-recall-tailscale` completed=True calls=4 llm=4 lat=22s
- rep=2 `r3-recall-none` completed=True calls=4 llm=5 lat=24s
- rep=3 `t1-create-bbr-cubic` completed=True calls=3 llm=3 lat=10s filed: TCP BBR vs CUBIC congestion control(new)
- rep=3 `t2-skip-commands` completed=True calls=1 llm=2 lat=4s
- rep=3 `t3-update-tailscale` completed=True calls=2 llm=3 lat=9s filed: Tailscale ACL tags vs rules(new)
- rep=3 `t4-mixed-cap-private` completed=True calls=2 llm=3 lat=31s filed: CAP theorem distributed systems(new)
- rep=3 `t5-thai-quantization` completed=True calls=3 llm=3 lat=41s filed: LLM quantization GGUF format(new)
- rep=3 `t6-hub-ada-nest-heartbeat` completed=True calls=2 llm=3 lat=27s filed: ada nest heartbeat escalation(new)
- rep=3 `t7-ephemeral` completed=True calls=1 llm=2 lat=10s
- rep=3 `o1-mark-learned` completed=True calls=2 llm=3 lat=3s filed: spaced repetition(upd)
- rep=3 `o2-push-review` completed=True calls=2 llm=3 lat=7s filed: tailscale acl basics(upd)
- rep=3 `o3-due-list` completed=True calls=1 llm=2 lat=6s
- rep=3 `r1-recall-spaced` completed=True calls=5 llm=5 lat=9s
- rep=3 `r2-recall-tailscale` completed=True calls=4 llm=4 lat=9s
- rep=3 `r3-recall-none` completed=True calls=4 llm=4 lat=28s

## Method notes
- `clawbot` = OpenClaw-shaped tool loop (same system-prompt duties + store CRUD tools) on `nvidia/nemotron-3.5-super-vl:free`. The real gateway on tony-omen is loopback:18789 — unreachable over tailnet — so the surface is emulated in-process.
- `clawbot` rep 1 returned model IDs: `nvidia/nemotron-3.5-super-vl:free`
- `clawbot` rep 2 returned model IDs: `nvidia/nemotron-3.5-super-vl:free`
- `clawbot` rep 3 returned model IDs: `nvidia/nemotron-3.5-super-vl:free`
- Structured-output counters (turn-2 loop change — args repair, schema-retry, forced-JSON escalation): clawbot: rep1: repairs=0 errors=0 retries=0 | rep2: repairs=0 errors=0 retries=0 | rep3: repairs=0 errors=0 retries=0
- Draft quality was not judged; saved HTML filings can be scored offline.
