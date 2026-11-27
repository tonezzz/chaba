---
category: operations
title: Adobe Stock image-model options (verified 2026-11-27)
status: active
---

# Adobe Stock image-model options

Source of truth for choosing an image/edit/upscale backend in `scripts/adobe-stock/`.
Findings were captured from public Hugging Face model pages with the AI Hub browser
capture bot; raw dumps live in the infra session folder. Wiki companion:
`Education:HF-Image-Model-Research-2026-11-27`.

## Current lanes (do not replace without a comparison)

- `gemini-image-edit.py` — Gemini Nano Banana via the Interactions API; primary edit lane, never lands to a campaign and never uploads to Adobe.
- `upscale-eval.py` — Real-ESRGAN (ncnn) and spandrel backends (SwinIR/HAT/RRDB/DAT), scored with laplacian variance, roundtrip PSNR/SSIM and flat-region texture gain. `bicubic` and `precomputed` are controls.
- `inpaint-mask.py`, `mask-picker.html`, `inpaint-composite.py` — mask and composite workflow.
- QC is Tony's gate throughout; no model verdict replaces it.

## Verified candidates

| Need | Model | Evidence | Use |
|---|---|---|---|
| Quantized local LLM | Qwen/Qwen3-8B-GGUF | Apache-2.0, 8.2B, 32k native / 131k YaRN, 5.6M downloads/month; Q4_K_M 5.03 GB, Q5_K_M 5.85 GB | local reasoning/eval work; Q4_K_M default |
| Image editing | Qwen-Image-Edit-2511 | 241k downloads, 1,592 likes, GGUF via unsloth | offline or batch edit alternative to Gemini |
| Image editing | FLUX.1-Kontext-dev | 149k downloads, 2,991 likes, GGUF ports | higher-cost quality option |
| Upscaling | Real-ESRGAN / SwinIR x2/x4 | existing backends already support them | keep in `upscale-eval.py`, do not add a parallel stack |
| Masking | BiRefNet / BiRefNet_HR-matting | 963k / 43k downloads | background removal and matting |
| Interactive masks | SAM2 small / tiny | 178k / 158k downloads | `mask-picker.html` / composites |
| Similarity / dedupe | CLIP vit-base-patch32 | 16.3M downloads | campaign coverage and reuse checks |
| Aesthetic pre-score | shunk031 aesthetics predictor v2 | 11k downloads | advisory only; never a QC gate |

## Verified comparison (2026-11-27, advisory only)

One bounded A/B (extended to three-way) on the frozen `comparison-b-sharp-leaves` source
(1024x576), scored with `upscale-eval.py` (no manual image generation; the harness runs
inference). Receipts in scratch `/tmp/opencode/ab-sr/`
(`realesrgan-sharp60.json`, `resshift-v1-s15.json`, `swinir.json`, `swinir-gan.json`).

| Metric | Incumbent (Real-ESRGAN x4plus, unsharp 60) | ResShift v1-s15 | SwinIR-M classical x4 | SwinIR-M real-SR (GAN) x4 | SwinIR-L real-SR (GAN) x4 |
|---|---:|---:|---:|---:|---:|
| laplacian_var output | 289.58 | 193.56 | 55.21 | 111.82 | 119.82 |
| roundtrip PSNR (dB) | 30.28 | 35.60 | 46.87 | 32.66 | 33.69 |
| roundtrip SSIM | 0.9613 | 0.9788 | 0.9981 | 0.9721 | 0.9761 |
| flat_region_lap_gain | 2.559 | 1.704 | 1.184 | 1.864 | 1.706 |
| wall_s | 0.0 | 6483.0 (CPU) | 442.3 (CPU) / 7.7 (MPS) | 429.6 (CPU) / 7.9 (MPS) | 15.7 (MPS) |

- ResShift v1-s15 wins both roundtrip metrics but is smoother and ~200x slower than the incumbent.
- SwinIR-M classical x4 posts the highest roundtrip PSNR/SSIM (46.87 / 0.9981) but the lowest
  laplacian (55.21) — i.e. it over-smooths. High roundtrip PSNR alone is misleading; it
  reflects near-bicubic smoothness, not retained texture. **Not a candidate for Adobe Stock
  as-is** (classical, non-GAN variant).
- SwinIR-M real-SR (GAN) x4 lands in the middle on every metric (laplacian 111.82, PSNR 32.66,
  SSIM 0.9721): more texture than classical but still less than ResShift (193.56) and the
  incumbent (289.58). No arm dominates on texture + roundtrip together. The GAN variant is the
  more honest SwinIR candidate but does not beat ResShift on texture or the incumbent on
  sharpness.
- SwinIR-L real-SR (GAN) x4 (136 MB, tested on kk-mac M4 Max via MPS) improves slightly over
  the M variant on every metric (laplacian 119.82 vs 111.82, PSNR 33.69 vs 32.66, SSIM 0.9761
  vs 0.9721) but still fails the guard (1.706) and does not beat ResShift on roundtrip metrics.
  The L variant is ~2x larger but only marginally better — not worth the extra compute for
  Adobe Stock. MPS runs in 15.7s vs 429.6s CPU fallback.
- `flat_region_lap_gain` (fixed guard: near-flat regions, mean-abs ratio, epsilon floor) is now
  **verified** for all four arms: incumbent 2.559, ResShift 1.704, SwinIR classical 1.184,
  SwinIR GAN 1.864. Only SwinIR classical (1.184) passes the ~1.2 threshold, but it
  over-smooths (laplacian 55.21). The incumbent adds the most invented texture (2.559).
- Hardware note: both SwinIR variants OOM on the GTX 1650 (4 GB) for a 1024x576 source and fall
  back to CPU (~7 min each). VRAM is a real constraint for larger sources.
- Decision rule (advisory): challenger advances only if it wins both PSNR and SSIM, keeps
  `flat_region_lap_gain` near ~1.2, and the wall-time gap is explicitly accepted. With the
  guard now working, only SwinIR classical passes ~1.2 (1.184) but it over-smooths (laplacian
  55.21). No arm clears all three criteria today; Tony is the QC gate.

## Rules

1. Compare any new backend against the existing lane with the repo's metric harness before adopting.
2. Keep credentials in env files; never print or copy keys into dumps, cards or KB docs.
3. No automatic uploads, licensing, publishing or campaign mutation — these stay human-gated.
4. Model downloads stay outside the repo; do not commit weights.
