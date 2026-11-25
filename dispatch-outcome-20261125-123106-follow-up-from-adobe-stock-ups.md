# Dispatch outcome — evaluate-resshift-rsd-class-distilled-sr-8d9c80

## What was done

Benchmarkged ResShift (v1 15-step + v3 4-step) and RSD (one-step distilled)
as mid-tier diffusion SR lanes on the comparison-b x4 asset, using the
OPS-1077 `upscale-eval.py` metric matrix — extended with a `precomputed`
backend + `--wall-s` so external-engine outputs score identically
(verified bit-exact vs the prior bicubic receipt: lap 5.35 / 45.44dB /
0.9967 reproduced).

All GPU work ran on tony-omen (idc02 has no GPU). The GTX1650's ~0.7-0.9GB
free VRAM (bge-rerank + ollama resident) cannot fit the VQGAN autoencoder,
so the working config is a **hybrid split**: diffusion UNet on cuda,
VAE encode/decode on CPU, 128px LQ tiles, all launches via
`run-cpu-job.sh` per Tony's load-guard. Repo patches (numpy2/torchvision/
SR_DEVICE/device-crossing/chop-128) are preserved as diffs.

## Result

| model | wall_s* | lap_var | rt PSNR | rt SSIM |
|---|---|---|---|---|
| ResShift v1-s15 | 6483 | 193.6 | 35.60 | 0.9788 |
| RSD one-step | 3596 | 174.6 | 34.85 | 0.9837 |
| ResShift v3-s4 | 3840 | 213.2 | 33.84 | 0.9806 |
| (prior) Real-ESRGAN | 32.4 | 130.5 | 32.20 | 0.9718 |
| (prior) SwinIR-M | 480 | 55.2 | 46.87 | 0.9981 |

*wall_s contention-inflated (host load 40-86); GPU-diffusion fraction is
seconds/tile — bottleneck is CPU-side VAE tiling.

**Verdict:** ResShift v1-s15 becomes the quality tier between the
Real-ESRGAN default and rented SUPIR — best generative fidelity measured
(+3.4dB PSNR vs Real-ESRGAN) with equal-or-more texture energy and a
non-T2I prior (low hallucination surface). RSD is the throughput tier on
GPUs where the VAE also fits. v3-s4 rejected (max texture, min fidelity).

## Deliverables

- `scripts/adobe-stock/upscale-eval.py` — `precomputed` backend (committed
  on dispatch branch `dispatch/20261125-123106-follow-up-from-adobe-stock-ups`)
- `docs/ssot/jobs/nest/2026-11-25-resshift-rsd-upscale-eval.yml` — trail
- `reports/resshift-rsd-upscale-eval-2026-11-25.md` + `reports/resshift-rsd-eval/`
  (gitignored locally; durable copies on
  `gdrive:ada-nest-adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001/60-upscale-eval/`:
  report md, `diffusion-outputs.tgz` with all 3 PNGs, patches, receipts)
- Card comms posted (setup, GPU-unblock, results, final).

## How to verify

- Receipts: `reports/resshift-rsd-eval/resshift-eval-receipts.tgz`
  (resshift-v1-s15.json, rsd-one-step.json, resshift-v3-s4.json) or
  `/tmp/resshift-eval/receipts/` on tony-omen.
- Re-run metrics: `upscale-eval.py --input src.png --backend precomputed
  --precomputed <out.png> --scale 4 --wall-s <s>`.
- Re-run inference: apply `patch-*-hybrid-gpu.diff` to the cloned repos,
  `SR_DEVICE=cuda run-cpu-job.sh <name> env ... inference*.py` on omen.

## Incidents worth noting

- Pure-CPU inference attempts caused a load ~57 / swap-full incident and
  earlyoom kills (incl. openjev) — same failure Tony flagged at 15:00.
  All later runs went through `run-cpu-job.sh`.
- An external actor twice relaunched v3-s4 as pure-CPU cpu-jobs (no
  `SR_DEVICE=cuda`) — cannot finish in reasonable time; noted on card.
- RSD chop256 peaked 7.6GB RSS → kernel OOM (killed openjev); chop128 fixed.

lessons:
- tony-omen GTX1650 shared-GPU SR: put diffusion UNet on cuda but pin the VQGAN autoencoder to CPU with device-crossing in encode/decode_first_stage — VAE activations OOM even at tiny tiles, UNet fits in ~0.7GB.
- upscale-eval.py now has `--backend precomputed --precomputed <png> --wall-s <s>` for scoring externally-produced upscales through the same metric matrix.
- ResShift/RSD inference writes output only at end-of-run — cpu-job timeout loses all tile progress; there is no checkpointing.
- On shared 4GB GPU hosts, check `nvidia-smi --query-compute-apps` before assuming VRAM is free — resident bge-rerank+ollama leave <1GB.
- python `str.replace` patches that don't match silently no-op — always grep/ast-verify the substitution landed (RSD decode device-crossing silently failed once, causing a cuda/cpu device mismatch).
