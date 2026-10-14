# Dispatch outcome — model-fleet-benchmark (2026-10-14, runner tony-omen)

Card `model-fleet-benchmark` → moved to **review**. All five plan deliverables landed.

## What changed (committed on dispatch branch, not pushed)

- `docs/ssot/infrastructure/ssot.model-tiers.yml` — NEW 6-tier registry (micro→superlarge) tiered by Q4_K_M footprint, per-host capability ceilings, multi_host measured verdicts.
- `scripts/bench/model-speed.py` — NEW harness: fixed 3-prompt suite (short_qa/gen500/thai), providers `ollama` / `openai` / `ssh_openai` (remote loopback over ssh, no listeners), records TTFT + decode tok/s + server VmHWM + warm/cold → `reports/model-bench/*.json` + `meta.model-bench.yml`.
- `scripts/bench/targets.{weekly,full}.yml` — cell lists.
- `docs/ssot/infrastructure/ssot.jobs.yml` — NEW job `model-bench` (tony_omen, Sun 05:15, cheap tiers).
- `docs/ssot/infrastructure/ssot.reports.yml` — NEW L1 node `model-bench`.
- `docs/ssot/infrastructure/ssot.model-routing.yml` — `bench_evidence` block.
- `docs/ssot/jobs/models/2026-10-14-model-fleet-bench.yml` — job report.
- `docs/ssot/ssot.registry.ssot-infrastructure.yml` — registered model-tiers file.
- CMS page `ada-cms-pages:model-fleet-benchmark` published with the rolled-up table.

## Measured results

Fleet matrix (decode tok/s median): omen GPU qwen3:0.6b 36 / llama3.2:1b 75 / llama3.2:3b 47 / phi3 17 / qwen2.5:7b 8.5 (partial offload) / gemma3:12b 3.2 (medium = batch-grade); idc03 3b-ollama 7.2, idc02 3b-llama.cpp 8.3, macbook 3b 8.9, dell micro (smollm2:135m) 116 tg.

Multi-host POC (llama.cpp `ggml-rpc-server` loopback + ssh -L tunnels, main=omen):
- 3B 50/50 omen+dell: LAN 8.29 / tailscale 6.90 vs 9.81 local (-15%/-30%)
- 3B fully-remote on dell via LAN: 8.83 (placement win — dell's CPU beats omen's capped i7)
- 27B (gemma-3-27b-it Q4_K_M 15.4GiB): local omen 1.25; omen+idc02 tailscale 24% 0.87
- 50/50 to idc02 crashed (peer OOM — idc02 had ~5G free); omen+dell LAN aborted when a ~4G shard starved dell's sshd (loadavg >60; recovered unharmed after kill)

**Verdict vs plan gate (<2 tok/s batch / >5 lane): fleet sharding is batch-only emergency tooling. For 27B-class, fit-one-host (omen RAM) beats every sharded config; no `large-lane` in the gateway.** RPC's only real win is placement (run small model on stronger remote CPU), not splitting.

## Surprises / lessons

- rpc-server dies hard on peer OOM (main aborts mid-stream). Check peer free-RAM before each run.
- tony-dell is not a safe shard peer during HA duty (~4.5G free is margin, not headroom).
- qwen3 TTFT includes thinking preamble (first visible token 6-12s) — instrumentation note, not a bug.
- First-run `peak_rss_mb` read the ollama parent not the runner child — fixed in `_find_server_pid`.

## Left behind / cleanup

- ggml-rpc-server stopped on dell/idc02/macbook; ssh -L tunnels down; micro-bench-llama.service back to inactive on idc02/macbook.
- tony-dell `~/model-bench/` left provisioned (llama.cpp b11583 tar extracted + smollm2 gguf — ~150MB total).
- omen `~/model-bench/` holds llama.cpp + Llama-3.2-3B (2.0G) + gemma-3-27b Q4_K_M (15.4G) GGUFs for future runs.
- Report artifacts copied to durable home: `~/CascadeProjects/chaba/reports/model-bench/` (reports/* is gitignored — per-checkout).

## Verify

- `node scripts/ssot-validate-all.mjs` — 2350/2350 valid.
- `python3 scripts/bench/model-speed.py --targets scripts/bench/targets.weekly.yml --runs 3` reproduces cells.
- CMS: `curl -s -X POST http://100.102.134.91:11027/v1/get -d '{"collection":"ada-cms-pages","key":"model-fleet-benchmark","lang":"en"}'`
