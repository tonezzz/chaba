# Dispatch outcome — adobe-stock-inpaint-defect-repair (2026-11-09)

Card: `adobe-stock-inpaint-defect-repair` (OPS-1109), runner idc02.
Continuation of dispatch 20261108-123518 (prior session died to OPS-1071
zombie-claim loop after landing the first inpaint artifact).

## What changed

- **cf-inpaint lane FIXED + first live run.** The 2026-11-08 429s were
  shared-pool quota, not a lane defect — but the payload format was also
  wrong: `@cf/runwayml/stable-diffusion-v1-5-inpainting` needs
  `image`/`mask` as **arrays of u8 ints (encoded file bytes)**, not b64
  strings ("failed to decode u8" / "array not in string"). Fixed
  `fetch_cf_inpaint` in `scripts/adobe-stock/land-render.py`. Ran the
  chair-wheels repair (fix3 + mask x475,y790,330x234): semantically
  correct 5-star base, but SD1.5 emits only 512x512. Composited the
  upscaled patch inside the feathered mask → landed
  `comparison-e-cf-inpaint-wheels` (1024x1024, sha `90c09847`) via
  `--lane local-file`. Patched region reads soft — quality-limited lane.
- **Q8 crop-mode inpaint evaluated to failure.** The prior session's
  wide-context crop run (832x528 @ x133,y496 — origin recovered by
  template-matching the crop against the source) had completed on omen
  but was never composited. Pulled, composited, visually QC'd:
  **rejected** — the Q8 cfg-7 run hallucinated a giant distorted
  foreground chair-base, worse than the tight-crop scoop-chairs failure.
  Not landed. Conclusion: low-cfg/low-step models (lightning cfg2/8-step)
  repair more faithfully than "quality" checkpoints for masked defects.
- **kk-mac diffusers lane** still blocked: kk-mac is ON the tailnet
  (active, direct) but idc02 carries no ssh key for kkkakk@kk-mac.
  Documented in runbook; duplicates the omen lane's function.
- **FLUX.1-Fill local** still blocked (gated weights + ~12GB RAM).
- **Runbook** `docs/ssot/jobs/nest/2026-11-08-adobe-stock-inpaint-lane.yml`
  updated to final lane statuses + revised decision (full-frame
  lightning over crop-mode Q8); also fixed pre-existing YAML quoting
  bugs that broke parsing. `ssot-validate-all` clean for this file
  (1 unrelated pre-existing error elsewhere).
- **QC note** appended to campaign `40-qc-review.md`: final lane
  comparison + recommendation (omen sd-cli lightning full-frame = default;
  cf-inpaint for fast/low-res). `SESSION.json` pending_decisions updated.
- **Lesson** `compositional-image-generation-layers-inpainting` updated
  via /lesson door → `lesson-a20f0c2294e2` (covers post 4162).
- **Commits** on `dispatch/20261109-090621-build-an-inpaint-lane-for-the-`:
  `a1592bbb3` (cherry-pick of prior tooling: inpaint-mask.py,
  omen-inpaint.py, local-file lane, tests, runbook) + `30b8ec853`
  (cf-inpaint u8 fix + final evaluation). Not pushed per dispatch rules.

## Result

Lane comparison complete; TWO masked-inpaint candidates landed for the
same defect (omen lightning = sharp winner, CF = soft but correct).
Deliverables met: lane comparison (QC doc + runbook), repaired
candidates, QC note, lesson. Tests: 4/4 pass.

## How to verify

- `rclone lsf gdrive:ada-nest-adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001/30-candidates/comparison-e-cf-inpaint-wheels/`
- QC the wheels region across `comparison-e-gemini-fix3-region`
  (defect), `-gemini-fix4-wheels` (no-op), `-cf-inpaint-wheels` (soft),
  `-omen-sdxl-inpaint-wheels` (sharp) — Tony visual QC pending.
- `python3 -m pytest tests/adobe-stock/test_inpaint_lane.py`

## Leftovers

- Scratch in `tmp/inpaint-lane/` (untracked) — composites, masks, the
  CF env pull. Omen `/tmp` still holds the inpaint inputs/outputs
  (~5MB, transient).
- Open asks live on the card + SESSION pending_decisions (Tony QC).
