# Colab GPU Image/Video Generation Research

## Experiment 01: Stable Diffusion 512×512 on Tesla T4

| Field | Value |
|---|---|
| Model | prompthero/openjourney |
| Prompt | a serene lake in the mountains at sunset, highly detailed |
| Resolution | 512×512 |
| Steps | 25 |
| Guidance scale | 7.5 |
| Seed | 42 |
| Device | Tesla T4 |
| Pipeline load time | 119.4 s |
| Generation time | 5.2 s |
| Peak VRAM | 3257.6 MB |
| Output image | `~/.local/colab-research/exp-01/generated.png` |
| Output JSON | `~/.local/colab-research/exp-01/report.json` |

## Observations

- `diffusers`, `transformers`, `accelerate` install and load cleanly on the Colab T4 runtime.
- Pipeline download + UNet load dominates wall time; actual 25-step inference is fast.
- VRAM stays well under the 15 GB T4 budget for 512×512 fp16 generation.
- HF downloads were unauthenticated (no `HF_TOKEN`); gated models (SDXL, FLUX, etc.) would need a token.

## Next

- Try 768×768 or SDXL/FLUX to measure VRAM/time scaling.
- Test short video (Wan 2.1 / SVD) once the image pipeline is trusted.
