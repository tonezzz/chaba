# Plan: Model size tiers + fleet inference benchmark + multi-host large-model feasibility

Status: proposal — awaiting review (2026-10-14)
Owner: devin / tony
Cards: TBD on approval

## 1. Size classification (Q4_K_M footprint — what actually decides fit)

| Tier | Params | Q4 mem | Examples |
|---|---|---|---|
| micro | <1B | ≤1 GB | gemma3:270m, smollm2:135m/360m, qwen3:0.6b |
| tiny | 1–3B | 1–2.5 GB | llama3.2:1b/3b, phi3.5-mini |
| small | 3–9B | 3–6.5 GB | llama3.1:8b, qwen2.5:7b, mistral:7b |
| medium | 9–30B | 7–20 GB | gemma3:12b, phi4:14b, qwen2.5:32b(19G) |
| large | 30–70B | 20–45 GB | qwen2.5:32b+, llama3.3:70b(43G) |
| superlarge | >70B | >45 GB | llama3.1:405b, deepseek-r1:671b — out of scope for this fleet |

Rule for tiering: the **Q4_K_M memory footprint**, not the marketing param count — that's what decides whether a host can hold it. A "small" model on a 4GB-VRAM GPU is one that fits in ~3.5GB.

## 2. Fleet fit map (from SSOT hardware records)

| Host | Compute | Fits (GPU-resident / CPU) |
|---|---|---|
| tony-omen | i7-9750H 6c@2.2GHz cap, 32GB RAM, **GTX 1650 4GB** | tiny–small on GPU; medium CPU-offload; large = 70B barely fits RAM at ~1 tok/s |
| tony-dell | CPU host (HA+apps) | micro–small CPU |
| tony-macbook | 16GB, Radeon Pro 450 2GB (Vulkan, no ROCm) | micro–tiny Vulkan, small CPU |
| idc01/02/03 | 4vCPU/16G VPS | micro–small CPU (idc03 is the busy one — benchmark, don't host) |
| mn01 | mini PC (offline now) | micro–tiny CPU |
| Colab T4 | 15GB VRAM, ephemeral | up to medium GPU-resident (gemma3:12b proven) |
| nest lanes | existing ollama student :8778 / heavy :8777 | already tiered: student≈small, heavy≈medium |

## 3. Benchmark method

One harness, fixed prompt set, identical across hosts — `scripts/bench/model-speed.py` (new):

- Per (host × model): pull once, then 5 timed runs of a fixed 3-prompt suite (short QA / 500-token generation / Thai prompt).
- Record: TTFT, decode tok/s, peak RSS/VRAM, warm-vs-cold delta.
- Store results as JSON under `reports/model-bench/` + meta node `model-bench` in ssot.reports.yml → system report sees it.
- Publish rolled-up table to CMS page `model-fleet-benchmark` (artifact-landing: publish is step 4 of the job, inside it).

Matrix (cap runtime per host):
- all hosts: micro + tiny
- omen/dell/macbook: + small
- omen + colab: + medium
- large: omen CPU only (23-45GB in 32GB RAM) and Colab if a ≤15GB variant exists (qwen2.5:32b Q4 ≈ 19GB — too big for T4; llama3.3:70b needs multi-host)

## 4. Multi-host large-model feasibility (the honest engineering answer)

Options for running a model that no single host can hold:

| Approach | How | Verdict for us |
|---|---|---|
| **llama.cpp RPC** (`rpc-server` per host) | splits layers across hosts; activations cross the network each token | Worth testing on LAN (omen+dell+macbook). Over tailscale (~100–900Mbps shared) decode collapses — expect <1 tok/s. OK for batch/offline, not interactive. |
| **exo** (exo labs mesh) | auto-shards, peer discovery | Same physics — network-bound. Better UX, same limits. |
| **vLLM tensor-parallel** | needs NVLink-class interconnect | Dead on tailscale. Skip. |
| **petals / swarm** | public volunteer swarm | Not for private workloads. |
| **Fit-one-host instead** | 70B Q2_K (~28GB) fits omen's 32GB | Degraded quality, ~1 tok/s CPU — still simpler than sharding. |

The physics that matters: each generated token sends activations host→host. Sequential, latency-additive, bandwidth-thin. Sharding across slow links only wins when the alternative is *can't run at all*.

**POC (phase-gated):** llama.cpp `rpc-server` on omen+macbook (+dell over LAN), one 27B model (gemma3:27b Q4 ≈ 17GB — no single host's GPU holds it, RAM does). Measure tok/s over LAN vs tailscale. Decision gate: <2 tok/s decode → fleet sharding is batch-only; >5 tok/s → worth a `large-lane` in the gateway.

## 5. Phases / deliverables

1. **Tier registry** — `docs/ssot/infrastructure/ssot.model-tiers.yml`: tier table + per-model entries + per-host capability ceiling. Gateway routing references it.
2. **Harness** — `scripts/bench/model-speed.py` + a systemd-runnable job (`ssot.jobs.yml` entry `model-bench`, host per-run param).
3. **Matrix run** — micro/small across fleet (~30 min/host incl. pulls).
4. **Multi-host POC** — llama.cpp RPC 2-host split of gemma3:27b, LAN vs tailscale comparison.
5. **Report** — CMS page `model-fleet-benchmark` + gateway routing-table update + card outcomes.

## 6. Open decisions for review

- Model list per tier — picks above are defaults; swap any (e.g. prefer qwen3 family for Thai).
- Include idc VPS CPU numbers at all? (cheap to run, likely all-slow — argues against hosting inference there).
- Multi-host POC: is 27B the right target, or go straight to the 70B that *needs* it?
- Where the harness runs from — tony-dell driving remotes over ssh+ollama REST is simplest (no agent installs).
