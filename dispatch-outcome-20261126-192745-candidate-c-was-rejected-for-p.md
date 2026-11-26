# Dispatch outcome — adobe-stock-illustration-pivot-test (OPS-1079, pass 2)

## What was done

Re-ran the OPS-1079 illustration-pivot task that a prior dispatch
(2026-11-08) had already attempted — this pass **corrects two factual
errors** in that earlier note and adds real visual QC of the asset.

1. Fetched `comparison-c-omen-sdxl.png` via its durable preview URL
   (assets.json) and inspected it: high-contrast flat/poster-style
   render — black-silhouette desk + two laptops, detailed foliage
   planters, saturated blue window panes, warm floor reflections.
   Reads as intentional flat design, but composition is rough
   (right-edge furniture crop, chair merged into black mass).
2. Verified current Adobe Stock rules (helpx.adobe.com, checked
   2026-11-26): raster illustrations are **JPEG-only sRGB**, and the
   **4MP minimum** applies — the earlier "PNG 1344x768 fine" claim was
   wrong on both axes. comparison-c is 1.03MP, so submission would need
   the proven Real-ESRGAN x4 path (→5376x3072, 16.5MP) plus JPEG/sRGB
   conversion. Gen-AI assets must be filed as asset-type Illustration
   with the "Created using generative AI tools" checkbox; "generative
   AI" in title/keywords is not required since 2023.
3. Drafted v2 metadata matched to the actual image (flat design /
   silhouette — NOT cartoon, which the spec suggested but doesn't
   describe this asset): title, alt title, 40 ordered keywords,
   suggested category Business (alt Lifestyle). Deliberately omitted
   "vector" (raster file) and "cartoon" (style mismatch).
4. **Decision: keep as second product line — asset is pilot, not
   product.** OPS-1078 already classified the omen sd lane as
   illustration-tier, so a second line is a consequence, not a new
   cost. If Tony's eyeball reads the silhouette as defect rather than
   style, discard this asset but keep the line (render flat design
   on purpose next time instead of salvaging a photo failure).
   No upload — metadata draft + QC note only, as specified.

## Artifacts (committed on dispatch branch, commit 738d432)

- `evals/adobe-stock-multirun/input/40-qc-review.md` — appended
  "Illustration pivot — comparison-c-omen-sdxl re-check (OPS-1079,
  2026-11-26)" section with corrected requirements, visual QC,
  metadata v2, decision.
- `docs/ssot/jobs/nest/2026-11-26-illustration-pivot-metadata.yml` —
  job doc (YAML-validated, 18 keys).

## How to verify

- `grep -n "re-check (OPS-1079, 2026-11-26)" evals/adobe-stock-multirun/input/40-qc-review.md`
- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/jobs/nest/2026-11-26-illustration-pivot-metadata.yml'))"`
- Card comms carry the final summary; card left for Tony's visual-QC
  decision on the silhouette style.

lessons:
- Adobe Stock raster illustrations are JPEG-only sRGB with a 4MP minimum — PNG is accepted only as a separate transparent-background class; verify helpx.adobe.com before claiming format compliance.
- preview_url fields in evals/adobe-stock-multirun/input/assets.json serve the actual PNGs — visual QC of campaign assets is possible without host access.
- sd-server manifest output_format is png, so every adobe-stock lane asset needs a JPEG+sRGB conversion step before any future upload — bake it into the landing pipeline if the program proceeds.
