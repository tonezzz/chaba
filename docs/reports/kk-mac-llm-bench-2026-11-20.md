# KK-Mac local LLM lane — inference smoke + model-size benchmark (2026-11-20)

Card: `kk-mac-local-llm-lane` · ref OPS-0966 · host: KKs-Mac-Studio
(M4 Max, 14 CPU cores, 32-core Metal GPU, 36 GiB unified memory, macOS 15)
Run path: read-only executor contract (`kk_mac_executor.run_contract`)
executed on tony-dell over the trusted `kkkakk@kk-mac` ssh hop — idc02
has no direct kk-mac ssh grant. Every call passed through the live
admission gate + MEM-1043 memory guard + independent verifier.

## Runtime check

Ollama Metal **0.40.8** already installed and healthy (login-bound,
loopback `:11434`). No install needed; MLX not required — Ollama is the
approved runtime in production use. Cached models:

| model | size on disk | class |
|---|---|---|
| qwen3:8b | 5.2 GB | 8B dense (lane default) |
| qwen2.5vl:7b | 6.0 GB | 7B dense VLM |
| llama3.2:3b | 2.0 GB | 3B dense |
| gpt-oss:20b | 13.8 GB | 21B MoE (~3.6B active) |
| qwen3:30b-a3b | 18.6 GB | 30B MoE (~3.3B active) |
| qwen2.5:32b | 19.9 GB | 32B dense |
| bge-m3 | 1.2 GB | embed |

**No 14B dense candidate is pulled** — the spec's 7–8B + 14B ladder has
an empty middle rung; the two MoE models were run as the nearest cached
stand-ins under the "20B+ only with resource evidence" rule. No model
was downloaded.

## Preflight (live, read-only)

heartbeat age ~119 s · load_1m 3.37 (< 4.0 cap) · ollama_ok · disk 55 GB
free · AC power · CPU 40 °C · free memory 82–84% · admission
`eligible=true`. Owner GUI apps (Adobe/Google) were open at moderate
CPU — this is the realistic shared-machine condition the gates exist
for.

## Results (verifier-gated contract calls)

| model / call | verdict | load | eval tokens | tok/s | mem free pre→min→post |
|---|---|---|---|---|---|
| qwen3:8b cold summary | **pass** | 0.81 s | 96 | 60.3 | 82→82→63% |
| qwen3:8b warm extract | **pass** | — | 28 | 60.3 | 65→65→63% |
| gpt-oss:20b cold | fallback | — | — | — | 84→**48**→48% |
| gpt-oss:20b warm | fallback | — | — | — | pre 49% (<60 floor) |
| qwen3:30b-a3b cold summary | **pass** | 8.6 s | 462 | **92.4** | 82→83→72% |
| qwen3:30b-a3b warm | fallback | — | — | — | 70→**20**→20% |

Artifacts: `evals/kk-mac-lane/bench-20261120/*.result.json` (full
contract records: admission, memory samples, usage, checks, verdict).

### Read of the evidence

1. **qwen3:8b remains the right lane model** — 60 tok/s warm, ~1 s warm
   load, 2/2 verified calls, memory comfortably inside the 60/50 guard.
   Matches the 15-job October baseline (mean 60.5 tok/s).
2. **qwen3:30b-a3b is fast but not lane-safe.** 92 tok/s (MoE ~3B
   active) with an 8.6 s cold load — but the 18.6 GB footprint drove
   free memory to **20%** during the second call (models overlap inside
   Ollama's keep-alive window). The guard failed closed; node recovered
   to 74% free with `/api/ps` empty. Also ignores `think:false`
   (visible chain-of-thought preamble → 4–5× token burn on short
   tasks). **Do not route lane traffic to it at current owner-memory
   conditions.**
3. **gpt-oss:20b never reached generation** — its ~14 GB load alone
   pushed free memory to 48–49%, breaching the 50% abort floor during
   the first call and the 60% pre-load floor on the second. Correct
   fail-closed behavior.
4. **20B+ verdict: resource evidence does NOT support >20B footprints
   on this 36 GiB host while owner apps are resident** — a ~14 GB load
   already eats the safety floor. Even a future dense 14B (~9–10 GB
   Q4) would sit ~10 points inside the floor; candidate only under
   near-idle memory (≥75% free). qwen2.5:32b (19.9 GB) stays
   benchmark-only for the same reason.
5. **MEM-1043 memory guard verified end-to-end in production path:**
   pre-load floor blocked call 4, during-run samples caught both real
   breaches, all violations produced fallback (not pass), and the host
   recovered cleanly. This closes the "no rerun until guard verified"
   hold from 2026-11-06.
6. Temperature stayed 40 °C throughout (limit 60). Energy/power:
   `powermetrics` needs root on macOS — not available in this lane;
   recorded n/a.

## Personal-file access — verified none

The entire on-host surface during the run was: `curl 127.0.0.1:11434`
(loopback Ollama), `memory_pressure -Q`, `vm_stat`, `sysctl
vm.loadavg`, `smctemp`, `df`, `pmset`, `ps`, `launchctl list`. No user
file reads, no `$HOME` traversal, no keychain/contacts/docs paths; the
executor code path (`kk_mac_llm.call_remote`) is a fixed ssh+curl
loopback call — there is no shell or filesystem bridge to the Mac.
Prompts carried synthetic fixture text only; artifacts landed on
tony-dell/idc02, nothing was written on kk-mac. Post-run `/api/ps`
empty — nothing left resident.

## Gates now in place

| gate | where | state |
|---|---|---|
| heartbeat freshness / ollama / disk / load / temp / node-busy | `kk_mac_admission.snapshot` + `local_snapshot` | live (this run: eligible) |
| memory 60% pre-load / 50% abort / critical-pressure | `kk_mac_memory` in executor | **verified live this run** |
| task-class bound (summary, operator_brief, structured_extract, safe_route; ≤6000 chars) | `kk_mac_llm.ALLOWED_TASKS` | live |
| drain file + `DEVNEST_KK_MAC_ENABLED=false` kill switch | worker `gate()` | live |
| **quiet-hours window `DEVNEST_KK_MAC_QUIET_HOURS=HH:MM-HH:MM` (ICT, wraps midnight; malformed → fail closed)** | worker `gate()` — **added this dispatch** | tested, opt-in (unset = unchanged) |
| LiteLLM fail-fast admission shim + `.deny` drain | idc03 `:11447` | live since 2026-11-14 |

Spec note: routing currently admits only the four bounded classes —
"deterministic-codemod suggestions / small bounded code tasks" are
deliberately **not** admitted yet; widening the class set needs its own
card (verifier contract for code output), not an in-session change.

## One-shot rollback (before any further launchd persistence)

Orderly, tested mechanisms — no new infra needed:

```bash
# instant drain (worker keeps running but admits nothing):
ssh kkkakk@kk-mac 'touch ~/.cache/kk-llm-worker.drain'
# full stop + unpersist:
ssh kkkakk@kk-mac 'launchctl bootout gui/$(id -u)/net.adanest.kk-llm-worker \
  && rm -f ~/Library/LaunchAgents/net.adanest.kk-llm-worker.plist'
# LiteLLM leg (idc03):
touch $XDG_RUNTIME_DIR/kkmac-admission-shim.deny   # shim 503s -> paid leg
systemctl --user stop kkmac-ollama-tunnel.service  # kills the tunnel
```

Every decline path is fail-closed to the next lane — rollback never
strands a card.

## Lane comparison (evidence: card-judgment corpus n≈98 + today's run)

| | kk-mac qwen3:8b | kk-mac qwen2.5:32b* | Flash Lite (paid leg) | Devin dispatch |
|---|---|---|---|---|
| marginal cost / task | **$0** | $0 | ~$0.10/$0.40 per MTok in/out (¢-scale) | paid plan tokens, session-scale |
| latency / bounded call | ~1–13 s, 60 tok/s | slower (dense 32B) | ~1–4 s | minutes (full session) |
| card-judgment action_acc | 0.674 | **0.857** | 0.49–0.52 | (not run — different class) |
| bounded-class pass rate | high (7/7, 3/3, 2/2 verified batches) | untested on contract | n/a (not schema-gated) | high, but oversized for the class |
| availability | gated (heartbeat/load/mem/quiet) | gated harder | ~always | ~always |
| intervention minutes | **~0 — auto-fallback** | ~0 | ~0 | ~0 + review |

\* benchmark-only per this report's memory evidence.
Takeaway: kk-mac already **beats Flash Lite on pass rate at $0** on the
card-judgment corpus and matches it on latency for bounded calls; its
cost is availability gating, which the fallback design absorbs. It
buys down Devin spend only for the four bounded classes — everything
else stays on Devin by design.

## Recommendations

- Keep `qwen3:8b` as the lane default; keep 20B+ models out of routing
  unless a future sample shows ≥75% free memory sustained (re-check
  after owner-workload changes).
- If a 14B rung is still wanted, `qwen3:14b` needs a pull approval —
  file as a request rather than downloading unilaterally.
- Set `DEVNEST_KK_MAC_QUIET_HOURS` (suggest `23:00-07:00`) in the
  installed worker plist at the next owner-approved maintenance window
  — the gate is live in code, the env is deliberately not flipped
  unilaterally.
