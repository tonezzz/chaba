# Outcome — adobe-stock-upscaler-eval (OPS-1077)

Evaluated open-source upscalers for the Nest Adobe Stock pipeline on
`comparison-b-sharp-leaves` (AS-2026-11-05-REMOTE-WORK-001, 1024x576
SDXL photographic) → x4 (4096x2304, 9.44MP). Ran the full classical-SR
matrix live on tony-omen; scored diffusion SR analytically (no fleet
host has the VRAM).

## Recommendation

**Default: Real-ESRGAN `realesrgan-x4plus` at native x4 via
`realesrgan-ncnn-vulkan`** — 32s/img on omen GTX1650 (Vulkan),
~19min/img on 9-core llvmpipe CPU (bit-equivalent output), deterministic,
no hallucination surface beyond GAN texture. `--dn 0.5` when the source
carries visible generation noise. **Alternate: SwinIR-M / HAT-S** for
max fidelity (46.9/45.4dB roundtrip PSNR, CLIP 0.9993) when a source is
already sharp and only needs the 4MP gate — output reads "clean resize".
**Rejected as default: SeeSR/OSEDiff/SUPIR** — 8.7–30GB VRAM, no fleet
host qualifies; hero-asset/rented-GPU lane only. (Follow-up idea carded
in the trail: ResShift/RSD-class distilled diffusion, ~0.5–1.2GB VRAM,
fits the GTX1650.)

## Key numbers (comparison-b → x4)

| backend | wall | lap | rt PSNR | rt SSIM | CLIP |
|---|---|---|---|---|---|
| realesrgan Vulkan | 32.4s | 130 | 32.2 | 0.972 | 0.970 |
| realesrgan dn0.5 | ~32s | 38 | 38.5 | 0.990 | 0.987 |
| realesrgan llvmpipe | 1130s | 130 | 32.0 | 0.973 | — |
| SwinIR-M (cpu) | 480s | 55 | 46.9 | 0.998 | 0.999 |
| HAT-S (cpu, crop) | 210s | 53 | 45.4 | 0.998 | — |
| Real-HAT-GAN (crop) | 197s | 135 | 32.1 | 0.972 | — |
| bicubic control | 0.7s | 5 | 45.4 | 0.997 | 0.998 |

## Found / fixed

- Adopted prior dispatch's v2 harness; fixed `run_spandrel` feeding
  cv2 BGR into RGB-trained models (channel swap → PSNR collapsed to
  ~22, would have wrongly failed all classical SR).
- Fixed ncnn device reporting (was logging first enumerated adapter
  instead of the selected `-g` index).
- Traps documented: ncnn `-s 3` on x4-only model → tile-scrambled
  output; `anime_6B` → black frame on this build; HAT full-frame OOMs
  under the dispatch cgroup; CLIP cosine can't see spatial corruption.
- Corrected lesson claim: x2 upscale (2.36MP) does NOT clear Adobe's
  4MP minimum — x4 is the floor for 1024x576 sources.

## Deliverables

- Report: `reports/upscaler-eval-2026-11-18.md` (also on Drive)
- Job trail: `docs/ssot/jobs/nest/2026-11-18-upscaler-eval.yml`
- Harness: `scripts/adobe-stock/upscale-eval.py` (v2 + fixes, committed
  on this dispatch branch — not pushed)
- QC artifacts: `gdrive:ada-nest-adobe-stock/.../60-upscale-eval/`
  (full outputs, receipts, detail crops for Tony visual QC)
- Education: lesson 4130 `ai-image-quality-ladder-upscaling-restoration`
  updated in place (eval section + 4MP correction + failure modes)
- Board: summary comment posted; request raised asking Tony to confirm
  the default (★ realesrgan vs swinir vs wait-for-diffusion).

## Verify

- `git log --oneline -1` on this branch shows the harness+trail commit.
- `rclone lsf gdrive:ada-nest-adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001/60-upscale-eval/`
- Receipts: `/tmp/as-eval/out/reports/*.json` on tony-omen (ephemeral).
- Worker integration plan is in the report §Worker integration plan —
  next concrete step is `upscale-worker.sh` + a `50-upscaled/` landing
  stage gated on QC verdict (worth a small follow-up card).
