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

One bounded A/B on the frozen `comparison-b-sharp-leaves` source (1024x576), scored with
`upscale-eval.py --backend precomputed` (no new image generation). Receipts in scratch
`/tmp/opencode/ab-sr/` (incumbent `realesrgan-sharp60.json`, challenger `resshift-v1-s15.json`).

| Metric | Incumbent (Real-ESRGAN x4plus, unsharp 60) | ResShift v1-s15 |
|---|---:|---:|
| laplacian_var output | 289.58 | 193.56 |
| roundtrip PSNR (dB) | 30.28 | 35.60 |
| roundtrip SSIM | 0.9613 | 0.9788 |
| flat_region_lap_gain | NaN | NaN |

- ResShift v1-s15 wins both roundtrip metrics but is smoother (lower laplacian) and ~200x slower.
- `flat_region_lap_gain` is NaN in both receipts, so the invented-texture guard is **unverified**.
- Decision rule (advisory): challenger advances only if it wins both PSNR and SSIM, keeps
  `flat_region_lap_gain` near ~1.2, and the wall-time gap is explicitly accepted. ResShift
  passes the first two only partially; Tony is the QC gate.

## Rules

1. Compare any new backend against the existing lane with the repo's metric harness before adopting.
2. Keep credentials in env files; never print or copy keys into dumps, cards or KB docs.
3. No automatic uploads, licensing, publishing or campaign mutation — these stay human-gated.
4. Model downloads stay outside the repo; do not commit weights.
