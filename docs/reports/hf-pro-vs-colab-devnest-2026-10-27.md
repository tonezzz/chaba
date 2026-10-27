# HF Pro vs Colab for DevNest — measured cost-benefit (2026-10-27)

Card: `hugging-face-pro-cost-benefit-for-colab-b22c9e` (OPS-0881).
Constraint honored: **no subscription, no pay-as-you-go job** — everything
below is measured from the existing Colab/Drive queue, free anonymous
probes, and official HF pages re-checked today.

## Verdict (up front)

**Defer HF Pro.** At measured utilization, pay-as-you-go HF Jobs would cost
~$6–12/mo — *less than one month of Pro* — and Colab Pro (~100 prepaid
compute units/mo, already paid) covers the workload at ~zero marginal cost.
Pro is algebraically worse than PAYG for Jobs spend at *any* usage level:
Pro total = $9 + max(0, X−5h)×$0.40 vs PAYG = X×$0.40, so Pro costs
≥$7/mo more unless ZeroGPU quota, 1TB private Hub, or 10 hosted ZeroGPU
Spaces are actually consumed. None of those fit the pack-queue pattern.

## Measured — Colab/Drive side (real queue artifacts)

| Metric | Value | Source |
|---|---|---|
| Heldout assessment battery (T4) | fp16 21.0 TFLOPs, bf16 2.2–2.4 TFLOPs, H2D 12.3 GB/s, D2H 13.0 GB/s, 5–6 s | `queue/assessments/devnest-heldout-{63c5ba23,bd3b5509}.json` (Oct 26/27 boots) |
| GPU-job time Oct 23–27 | **4.62 job-hours** across 45 runner launches (23:0.72h, 24:2.59h, 25:0.53h, 26:0.04h, 27:0.73h) | summed `DONE Ns` in all `queue/log-*.txt` |
| Pack completions | all **42** `packs/*/done` markers in the store are Oct 23–27 (queue now drained; 41/42 done) | `rclone lsl gdrive:ada-nest/packs/ --include done` |
| Oct 27 session shape | 48 min wall, ~44 min GPU (kk-video-embeds 2605 s), warmup 30 s hid 31 s cache-restore prep | `log-20261027-0454.txt` |
| Cache restore Drive→Colab | 12.6 GB `hf-hub.tar.zst` ≈ 223 s (~56 MB/s incl. zstd) | KB `colab-mcp-jobs.md`, boot 326f1d48 |
| Drive artifact landing (rclone API, idc02 probe) | 64 MB up in 9.2 s (6.9 MB/s), server-side visible +2.6 s | live probe today |
| DriveFS FUSE landing on Colab | ~60 s+ listing lag; one 13 GB tar LOST on VM restart before flush | KB (observed incident) |

## Measured/documented — HF side (free probes + official pages, 2026-10-27)

| Metric | Value | Source |
|---|---|---|
| HF CDN anonymous download → idc02 WAN | **40.8 MB/s** (988 MB Qwen2.5-0.5B shard in 24.2 s) | live probe today |
| Drive pull → idc02 WAN (same host, rclone) | 28.9 MB/s (1 GiB slice of `hf-hub.tar.zst`) | live probe today |
| HF Jobs | **no free tier** — "available to any user with a positive credit balance"; CPU Basic $0.01/h, T4-small $0.40/h, billed/min, 50 GB ephemeral disk, no inter-job cache | huggingface.co/docs/hub/jobs-pricing |
| ZeroGPU quotas | anonymous 2 min/day (low pri), free account 5 min/day, PRO 40 min/day (highest), overage $1/10 min | huggingface.co/docs/hub/spaces-zerogpu |
| ZeroGPU shape | **Gradio-SDK Spaces only** — `@spaces.GPU` functions, ≤~120 s calls, half/full RTX Pro 6000 Blackwell, model lives in the Space | same |

**Why no live HF job ran:** `hf jobs` requires (a) an HF token (none exists
on any fleet secrets store — Colab runtimes hold one, fleet hosts don't)
and (b) a positive credit balance — i.e. pay-as-you-go, which the card
explicitly gates on Tony's approval. A bounded probe would cost ~$0.07
(10 min t4-small) or ~$0.01 (cpu-basic), so it is cheap but still spend.
ZeroGPU anonymous (2 min/day) can only call an *existing* Space's Gradio
function — it cannot run our assessment battery; hosting our own ZeroGPU
Space needs a free account (2 Spaces max) and would still be the wrong
shape for batch work.

## Monthly utilization (measured, pack era)

- 4.62 GPU-job-hours / 5 days ≈ **0.9 h/day → ~28 T4-job-hours/month**
  if cadence holds; realistic range **15–30 h/mo** (queue drains between
  bursts — 41 of 42 packs already done).
- On Colab Pro units (~2 CU/T4-h): ~56 CU/mo, inside the ~100 CU/mo
  allotment — marginal cost ≈ $0.
- Equivalent HF Jobs PAYG: 15–30 h × $0.40 = **$6–12/mo**.
- Same usage under Pro: $9 + overage ≈ **$16–21/mo**.

## Fit for the DevNest pack-queue pattern

| Need | Colab + Drive (current) | HF Jobs | ZeroGPU |
|---|---|---|---|
| Arbitrary pack runner | yes (queue/runner.py) | yes (Docker/command) | **no** — Gradio functions only |
| Launch path | notebook + MCP/Drive lease | clean API/CLI (`hf jobs run`), scheduled jobs exist | per-call quota |
| Cold cache | Drive tar restore ~56 MB/s, warm-cache no-ops | re-download per job (ephemeral), or pull pinned tar from Hub repo | model pinned in Space |
| Artifact landing | DriveFS lag ~60 s (verify-before-mark required); rclone-API 2.6 s | Hub upload = durable at API return | inside Space output |
| Queue/control-plane SSOT | Drive (today's standard — keep) | none native; would egress | none |
| Cost at ~28 h/mo | ~$0 marginal (prepaid Pro units) | ~$11 PAYG | not applicable |

## Where HF Hub *is* worth using now (free)

- **Pinned private artifacts/checkpoints**: current private need ≈ 30 GB
  (12.6 GB hf-hub tar + 17.7 GB ollama tar) — within free-account private
  storage; Hub upload gives immediate durable landing vs DriveFS lag.
  Optional mirror, not a migration: Drive stays the queue/control-plane SSOT.

## Revisit triggers

1. HF-Jobs spend would exceed ~$9/mo on PAYG **and** a Pro extra gets used.
2. A real hosted-ZeroGPU-Space product surface exists (public demo endpoint).
3. Private pinned artifacts outgrow free-tier storage (~>100 GB of
   non-reproducible checkpoints).
4. Colab Pro lapses or quota stops covering the queue.

## Bounded live probe (if Tony wants the missing datapoint)

One `hf jobs run --flavor t4-small --timeout 10m` job executing the
devnest-heldout battery + a Hub-artifact upload: ~$0.07 spend + an HF
token in `~/.config/secrets/`. Board request carries the options.
