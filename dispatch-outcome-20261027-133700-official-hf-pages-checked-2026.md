# Dispatch outcome — HF Pro cost-benefit for Colab/DevNest

Card: `hugging-face-pro-cost-benefit-for-colab-b22c9e` (OPS-0881). Runner: idc02.

## What was done

Ran the bounded comparison the card asked for **without any subscription or
pay-as-you-go job**: real Colab queue artifacts + free anonymous probes +
official HF pages re-checked 2026-10-27.

**Measured (Colab/Drive side, real artifacts):**
- `devnest-heldout-assessment` on real T4 boots (Oct 26 `63c5ba23`, Oct 27
  `bd3b5509`): fp16 21.0 TFLOPs, bf16 2.2–2.4, H2D 12.3 / D2H 13.0 GB/s,
  battery 5–6 s.
- Utilization: summed `DONE` durations in all 45 `queue/log-*.txt` →
  **4.62 GPU-job-hours Oct 23–27** (~0.9 h/day → **15–30 T4-job-h/mo**);
  all 42 `packs/*/done` markers are from this same 5-day window (queue now
  drained).
- Cold-cache: Drive→idc02 pull 28.9 MB/s (1 GiB of `hf-hub.tar.zst`);
  Drive→Colab restore ~223 s/12.6 GB (~56 MB/s, KB-verified).
- Artifact landing: Drive rclone-API 64 MB in 9.2 s, server-visible +2.6 s;
  DriveFS on Colab ~60 s lag (13 GB loss incident on record).

**HF side (free probes + docs):**
- HF CDN anonymous download → idc02: **40.8 MB/s** (988 MB shard).
- HF Jobs: **no free tier** — positive credit balance required; T4-small
  $0.40/h, cpu-basic $0.01/h, per-minute billing, ephemeral disk.
- ZeroGPU: anon 2 min/day, free acct 5, Pro 40 — but **Gradio-Spaces calls
  only**, cannot host `queue/runner.py`.
- A live HF job was NOT run: needs an HF token (none on fleet secrets) AND
  a positive credit balance — i.e. PAYG spend, gated on Tony's approval.

## Result / decision math

**Defer Pro.** At ~15–30 T4h/mo: PAYG Jobs ≈ $6–12/mo; Pro ≈ $16–21/mo.
Pro is ≥$7/mo worse than PAYG at *any* usage on Jobs spend alone — it only
pays off if ZeroGPU quota / >100 GB private Hub / hosted Spaces get used,
none of which fit the pack-queue pattern. Colab Pro (already paid,
~100 CU/mo) covers the workload at ~zero marginal cost. Drive stays
queue/control-plane SSOT; free-tier private Hub is optionally useful for
pinned artifacts (~30 GB need today).

## Artifacts

- `docs/reports/hf-pro-vs-colab-devnest-2026-10-27.md` — full report.
- `docs/ssot/jobs/devnest/2026-10-27-hf-pro-cost-benefit-assessment.yml` —
  run record.
- Board: findings comment + decision **request** posted (options: ★ defer /
  ≤$1 bounded PAYG probe / free-token-only). No answer at session end.

## How to verify

- `rclone lsl gdrive:ada-nest/packs/ --include done` → 42 markers, Oct 23–27.
- `rclone cat gdrive:ada-nest/queue/assessments/devnest-heldout-bd3b5509-*.json`
  → T4 battery numbers cited above.
- Card comms show the summary + the open `hf-pro-decision-…` request.

## Follow-ups noted

- No HF token exists on fleet secrets (`~/.config/secrets/`); the only
  HF_TOKEN lives inside Colab runtimes (pack yml refs). If Tony picks
  option (b)/(c), a `hf.env` secret + `huggingface_hub` install on one
  exec host is all that's needed.
- Live HF Jobs probe stays gated on the board request — ~$0.07 for a
  10-min t4-small run of the heldout battery.
