# QC Review

## Candidate A — `remote-work-home-office-001` (baseline)

File: `30-candidates/remote-work-home-office-001/kk-sdxl-remote-work-home-office-001.png`
Decision: **keep for comparison**

Note: plant leaves are slightly blurry. Keep this asset as the baseline comparison; do not treat it as the final Adobe Stock submission yet.

## Candidate B — `comparison-b-sharp-leaves`

File: `30-candidates/comparison-b-sharp-leaves/comparison-b-sharp-leaves.png`
Manifest: `30-candidates/comparison-b-sharp-leaves/comparison-b-sharp-leaves.manifest.json`
Source: Nest pack `kk-mac-image-render-poc`, request `render-002-comparison-b`, worker `KKs-Mac-Studio.local-31004`
sha256: `4d5694c0ee3a4249d2fa69cf48d36a7121ce7c4ce01a7f55ce1a0243e535535a`
Decision: **revise**

QC note: plant leaves improved, but the floor behind the door and the chair surface under the table look weird.

## Candidate C — `comparison-c-clean-surfaces` (rendering)

Request: `render-003-comparison-c`
Goal: keep the improved leaf sharpness while fixing floor/chair geometry artifacts.
Status: **render dispatched, awaiting result**

## Comparison C — omen SDXL fallback (2026-11-07)

Rendered on tony-omen `sd-server` (SDXL-Lightning 4-step, CPU) after KK-Mac
stayed offline ~17h and the Gemini lane remained down (402 credits
depleted). Job `job_6aeea32e_00000001`, ~71 min wall under load ~29.

- File: `30-candidates/comparison-c-omen-sdxl/comparison-c-omen-sdxl.png` (1344x768, 1.0 MB)
- Manifest: `comparison-c-omen-sdxl.manifest.json`
- SHA-256: `905631838a88e177dac783b4c35ee75b5bead3db15274ec3261c3f5ce5c3750d`
- Prompt targeted B's defects: consistent hardwood floor, realistic chair
  proportions/surface, no warped floor or melted furniture; kept crisp
  plant leaves + left copy space.

QC checklist vs B: floor behind door, chair surface under table, plant
sharpness, composition/copy space, artifacts, commercial usefulness.

Decision: keep / reject / revise — Tony visual QC required. Adobe upload
remains manual and is NOT authorized.

## Comparison C QC result (2026-11-07)

**Decision: reject for photorealism.** C reads as color paint, not a
photograph. Likely cause: omen lane runs SDXL-Lightning 4-step — few
steps produce painterly, low-detail output. KK-Mac's 20-step SDXL render
(candidate B) was photographic. Options: retry realism on KK-Mac when
awake, try 8-step Lightning on omen, or pivot to illustration keywords
(Adobe Stock sells illustrations/vectors/cartoons as separate categories).

## Exploration tracks opened (2026-11-07)

- Realism lane: KK-Mac staged render-003 (20-step SDXL) when host wakes;
  Gemini image lane once API credits are topped up (OPS-1048 confirmed AI
  Pro does not fund API usage).
- Quality ladder lesson filed: Education post 4130
  (ai-image-quality-ladder-upscaling-restoration).
- New cards: OPS-1077 upscaler eval, OPS-1078 omen full-SDXL experiment,
  OPS-1079 illustration-pivot keyword test for comparison-c.

## Comparison E QC result — cf-flux-schnell (2026-11-07)

**Decision: revise.** Plant leaves look good — FLUX.1 schnell delivers
real sharpness. Wall corner geometry looks weird. Next revision should
add wall/corner/corner-line consistency to prompt + negatives
(warped walls, impossible corners, converging lines).

## comparison-d-omen-sdxl-q8 — omen-sd lane (landed 2026-11-07T11:10:35.894371+00:00)

- File: `30-candidates/comparison-d-omen-sdxl-q8/comparison-d-omen-sdxl-q8.png` (1344x768, 1878962 bytes)
- SHA-256: `199027ffd31a2eff9c8cb04c88fa46e791125ad61c7066f4020615bd5fab6691`
- Job: `job_6aeee1d0_00000000`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-d-omen-sdxl-q8 — Tony QC (2026-11-07)

**Decision: revise.** "Look smooth and good, but doesn't feel like
photorealistic. Maybe more sharpen." Upscale + sharpen pass in flight
(Real-ESRGAN x4plus on tony-dell); will land as comparison-d-x4 for
re-QC. Realism gap likely model ceiling (SDXL Q8 CPU), not resolution.


## comparison-e-gemini-wallfix — gemini-image lane (landed 2026-11-07T12:19:32.689338+00:00)

- File: `30-candidates/comparison-e-gemini-wallfix/comparison-e-gemini-wallfix.png` (1024x1024, 1767675 bytes)
- SHA-256: `e67e1f6deeec9b3bb9dbddbd0109a1dd930a8559011ef3bb9fae51c16417a811`
- Job: `gemini-2.5-flash-image`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-d-x4 — postprocess lane (landed 2026-11-07T12:24:19.885169+00:00)

- File: `30-candidates/comparison-d-x4/comparison-d-x4.png` (5376x3072, 25297085 bytes)
- SHA-256: `5bf3881619178701c1c4b3f6d76b47355e5d9dec4cb3f77544d217a0eca409c5`
- Job: `local-ncnn`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-d-x4-sharp40 — postprocess lane (landed 2026-11-07T12:24:46.833994+00:00)

- File: `30-candidates/comparison-d-x4-sharp40/comparison-d-x4-sharp40.png` (5376x3072, 21095328 bytes)
- SHA-256: `1ef079bb83c8f08af1fe0e039684a92469974a913b700539be61bfc32712c09e`
- Job: `local-ncnn`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-d-x4-sharp60 — postprocess lane (landed 2026-11-07T12:25:14.887552+00:00)

- File: `30-candidates/comparison-d-x4-sharp60/comparison-d-x4-sharp60.png` (5376x3072, 22417918 bytes)
- SHA-256: `b8b27a00c9f293f6458a75b2fb53d8629aa3e284da59784cfd60327c1b261697`
- Job: `local-ncnn`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-g-omen-sdxl-q8-wallfix — omen-sd lane (landed 2026-11-07T13:15:38.647124+00:00)

- File: `30-candidates/comparison-g-omen-sdxl-q8-wallfix/comparison-g-omen-sdxl-q8-wallfix.png` (1344x768, 1760772 bytes)
- SHA-256: `a46d9e58577f8c058540570f8779bcffbfaf38169f84fec4a33b1fcf63e2d5df`
- Job: `job_6aeefe1a_00000001`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-e-gemini-wallfix — gemini-image edit (landed 2026-11-07)

**Decision: revise.** Wall-corner fix works mid-wall, but the vertical
corner does not align at the floor; the shelf near the corner looks
floating (needs contact shadow/grounding). Overall image reads darker
and flatter than KK-Mac candidate B — brightness/mood gap noted.
Next repair should combine: floor-corner alignment + shelf grounding +
relight (soft morning window light). Mask-picker UI live for region
selection: http://192.168.2.67:8777/

## comparison-e-gemini-fix2 — gemini-image lane (landed 2026-11-08T00:38:21.718893+00:00)

- File: `30-candidates/comparison-e-gemini-fix2/comparison-e-gemini-fix2.png` (1024x1024, 1829666 bytes)
- SHA-256: `a127566c1ec6ce53a52909c95948291558de9ef5c7d3f906f501213dad39feab`
- Job: `gemini-2.5-flash-image`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-e-gemini-fix2 — Tony QC (2026-11-08)

**Decision: revise.** Brightness/relight worked — leaves sharp. But the
room corner is still not aligned top-to-bottom and the shelf still
looks floating. Full-image Gemini edits fix mood but cannot hold
vertical geometry. Next: picker-selected region repairs (corner strip,
shelf) or masked inpainting.

## comparison-e-gemini-fix3-region — gemini-image lane (landed 2026-11-08T02:59:49.941869+00:00)

- File: `30-candidates/comparison-e-gemini-fix3-region/comparison-e-gemini-fix3-region.png` (1024x1024, 1903022 bytes)
- SHA-256: `e519f5e538d890a1625dfc23b5151e7eb7b93eeb1f76d740b286c77c170a74d0`
- Job: `gemini-2.5-flash-image`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-e-gemini-fix3-region — Tony QC (2026-11-08)

**Decision: revise (corner fixed).** Picker-driven region edit
(request 20261108T025838Z, region x177 y290 w319 h559) fixed the wall
corner — first successful targeted repair. Remaining defect: chair
wheels. Region-select loop proven.

## Illustration pivot — `comparison-c-omen-sdxl` (OPS-1079, 2026-11-08)

The photorealism rejection ("reads as color paint") is a **category
mismatch, not necessarily a quality defect** — 4-step SDXL-Lightning
produces painterly/flat output that suits Adobe Stock's
illustration/cartoon categories, which are sold separately from
photography.

### Category check

- Adobe Stock accepts raster illustrations as PNG/JPG; cartoon/flat-design
  is a listed contributor style. PNG 1344x768 @1.0 MB is within limits
  (PNG fine for illustration; JPEG preferred only for photos).
- Same keyword/title rules apply; must be original (it is — self-rendered).
- No upload authorized — metadata draft + QC note only.

### Draft metadata (illustration category)

- **Title:** Modern home office flat-design illustration, remote work concept
- **Keywords:** remote work, work from home, home office, freelancer,
  digital nomad, laptop workspace, video call, flat design, illustration,
  modern office, cozy workspace, indoor plants, ergonomic desk, minimal,
  productivity, online meeting, creative professional

### Decision: **keep as second product line — pending Tony visual QC**

Rationale: zero marginal render cost, the "defect" aligns with a real
buyer category, and the asset already has durable preview URLs in the
reuse index. Risk: 4-step SDXL can still produce anatomy/geometry
artifacts that hurt illustration quality too — needs the same human eyeball
that rejected it for photo. If it passes visual QC as illustration, file
under illustration keywords; if artifacts are visible, discard.

## Inpaint lane evaluation — wheels defect (2026-11-08, OPS-1109)

Same defect — chair wheels on `comparison-e-gemini-fix3-region`
(region x=475 y=790 w=330 h=234 of 1024x1024) — driven through every
available repair lane:

- **gemini-image region-edit (control)** → `comparison-e-gemini-fix4-wheels`
  sha `0dc1094c`. Near-no-op: same blobby ball-casters, entire frame
  re-rendered. Confirms prompt-only "edit region x,y,w,h" under-edits
  small geometry and cannot preserve approved pixels.
- **omen sd-cli SDXL masked inpaint + composite** →
  `comparison-e-omen-sdxl-inpaint-wheels` sha `1e9d1ade`. Masked denoise
  (`-i init --mask mask`, sdxl-lightning-4step.q4_0, 8 steps, ~45min
  CPU on loaded omen) regenerated only the region: new black five-star
  base with proper caster wheels + floor contact shadows. Raw latent
  output VAE-re-encodes the whole frame (softens everything); the landed
  file is the masked region composited back onto the original inside
  the feathered mask — outside-mask pixels preserved.
- **omen sd-cli sdxl-base-1.0-Q8 (crop mode, 640x448, 16 steps)** →
  FAILED semantically (not landed): the tight crop gave too little
  context — the model hallucinated two scoop chairs into the region.
  Retrying with a wide-context crop (chair fully in frame, 832x528) —
  rule: the crop must include the object's semantic context, not just
  bbox + fixed margin.
- **cf-inpaint (Workers AI SD1.5)** → BLOCKED all day: 429
  neurons-exhausted at 01:33, 05:40, 06:30 UTC — the shared free
  10k/day pool did not reset or is being reconsumed by another
  consumer. Lane code verified; retry when budget returns.
- **FLUX.1-Fill local** → BLOCKED: needs ~10GB of license-gated HF
  weights (city96 gguf repo 401 without token) + ~12GB free RAM — no
  host qualifies (omen 6.5GB free / swap 96% full, kk-mac asleep).
- **diffusers SDXL-inpaint on kk-mac** → BLOCKED: host asleep (ssh
  timeout, tailscale last-seen 1d). Runnable command in the lane
  runbook.

Lane tooling landed on the dispatch branch: `inpaint-mask.py`
(box/polygon→feathered mask), `omen-inpaint.py` (ssh sd-cli driver),
`land-render.py --lane local-file` (lands CLI-produced files through
the standard verify+manifest path).

Decision: **pending Tony visual QC** — compare the wheels region across
fix3-region / gemini-fix4-wheels / omen-sdxl-inpaint-wheels (and the
Q8 crop variant when it lands). If the omen composite passes, the
chair-wheels defect is resolved without a re-roll.

## comparison-e-cf-inpaint-wheels — local-file lane (landed 2026-11-09T02:10:57.845668+00:00)

- File: `30-candidates/comparison-e-cf-inpaint-wheels/comparison-e-cf-inpaint-wheels.png` (1024x1024, 1379709 bytes)
- SHA-256: `90c09847320fe593525c1097106cf0ceeaec73d059923b96c4def08cd8affd1d`
- Job: `tmp/inpaint-lane/fix3-wheels-cf-composited.png`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## Inpaint lane evaluation — FINAL (2026-11-09, OPS-1109)

All lanes now resolved. Same defect throughout: chair wheels on
`comparison-e-gemini-fix3-region` (mask x=475 y=790 w=330 h=234,
feathered). Verdict per lane:

- **omen sd-cli sdxl-lightning full-frame masked denoise + composite**
  → `comparison-e-omen-sdxl-inpaint-wheels` sha `1e9d1ade` — **the
  winner**. Semantically correct 5-star base + casters, patched region
  sharp, outside-mask bit-exact. Slow (~45min CPU under load ~9) but
  works unattended.
- **cf-inpaint (Workers AI SD1.5)** → `comparison-e-cf-inpaint-wheels`
  sha `90c09847` — **works now, quality-limited**. Quota returned
  2026-11-09; correct payload = image/mask as arrays of u8 ints (file
  bytes), NOT b64 strings (land-render.py fixed). Repair is
  semantically correct, but SD1.5 emits only 512x512 — the landed file
  is the 512 output upscaled and composited inside the mask, so the
  patched region reads soft vs the sharp omen result. Fine for
  web-res assets, weak for stock. Seconds-fast, $0.00/step.
- **omen sd-cli sdxl-base-1.0-Q8 crop mode** → **FAILED twice, not
  landed.** Tight crop (640x448, bbox+margin): hallucinated two scoop
  chairs. Wide crop (832x528 at x133,y496 — chair fully in frame,
  16 steps cfg 7, ~23min): hallucinated a giant distorted foreground
  chair-base/wheel sculpture, far worse than the defect. Q8 at
  cfg 7 over-imagines in the masked region; lightning at cfg 2 /
  8 steps stays conservative. Don't assume higher-quality model =
  better repair — low-step low-cfg models are *more* faithful to
  surviving context.
- **gemini-image region-edit (incumbent)** →
  `comparison-e-gemini-fix4-wheels` sha `0dc1094c` — near-no-op on
  wheel geometry; re-renders the whole frame. Fine for mood/lighting
  edits, wrong tool for small-geometry defects.
- **flux-fill-local** → still blocked: ~10GB gated weights + ~12GB RAM;
  no qualifying host.
- **diffusers SDXL-inpaint on kk-mac** → still blocked: kk-mac is on
  the tailnet but idc02 carries no ssh key for it (Permission denied).

**Recommendation:** default defect-repair lane = omen sd-cli
lightning full-frame masked denoise + feathered-mask composite. Use
cf-inpaint when latency matters and 512-native output is acceptable.
Inpaint repairs turn "revise" QC verdicts into surgical edits — but
the repaired region still needs human QC; geometry hallucination is
the failure mode, not seams.

Decision: **pending Tony visual QC** — compare wheels region across
fix3-region (defect), gemini-fix4-wheels (no-op), cf-inpaint-wheels
(soft), omen-sdxl-inpaint-wheels (sharp) in 30-candidates/.

## comparison-h-omen-sdxl-q8-cprompt — local-file lane (landed 2026-11-25T02:36:06.209125+00:00)

- File: `30-candidates/comparison-h-omen-sdxl-q8-cprompt/comparison-h-omen-sdxl-q8-cprompt.png` (1344x768, 1975532 bytes)
- SHA-256: `13ab4de2420197dd0ea19140343582aef0b51e102fecad50d760dfc5950fc9fb`
- Job: `/tmp/ops1078-compare/comparison-h-omen-sdxl-q8-cprompt.png`

QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.
Decision: keep / reject / revise — Tony visual QC required.

## comparison-h-omen-sdxl-q8-cprompt — OPS-1078 controlled re-run (2026-11-25)

- File: `30-candidates/comparison-h-omen-sdxl-q8-cprompt/comparison-h-omen-sdxl-q8-cprompt.png` (1344x768, 1975532 bytes)
- SHA-256: `13ab4de2420197dd0ea19140343582aef0b51e102fecad50d760dfc5950fc9fb`
- Job: `job_6b063236_00000000` on tony-omen :8400 (parallel sd-server, sdxl-base-1.0-Q8_0.gguf, 20 steps, cfg 7.0, euler_a, seed 20261106)
- Prompt: verbatim candidate-C prompt (recovered from the original submission script)

Same-prompt comparison set for the photorealism question (OPS-1078):
C = sdxl-lightning Q4 (job_6aeea32e), D = sdxl-base Q8 (job_6aeee1d0),
H = sdxl-base Q8 verbatim-C-prompt controlled re-run (this asset).
Laplacian-variance sharpness proxy: C 1218 / D 1670 / H 1531 — Q8 holds
~26-37% more fine detail than Lightning. Prior Q8 QC (D): "smooth and
good, but doesn't feel photorealistic" — H is the same model class;
expect the same band. Decision: keep / reject / revise — Tony visual
QC required; photoreal lane stays kk-mac/gemini/CF.

## Illustration pivot — `comparison-c-omen-sdxl` re-check (OPS-1079, 2026-11-26)

Second pass — supersedes the 2026-11-08 section above, which had two
factual errors in the category check.

### Category requirements (verified vs helpx.adobe.com, 2026-11-26)

- Gen-AI images submit **as Illustration asset type** with the
  "Created using generative AI tools" checkbox; fictional people/places
  also get "People and Property are fictional" (none here — generic
  interior, no people). "generative AI" is NOT needed in
  title/keywords (dropped as a requirement in 2023).
- **Illustration = JPEG only (sRGB)** for raster — PNG is NOT accepted
  as an illustration format; PNG submissions are a separate class for
  transparent-background assets. Prior "PNG fine" note was wrong:
  the file must be converted to JPEG before upload.
- **Minimum resolution 4MP** (max 100MP, ≤45MB). comparison-c is
  1344x768 = 1.03MP — below minimum; prior "1344x768 fine" note was
  wrong. Proven path: Real-ESRGAN x4 (tony-dell local-ncnn lane,
  same as comparison-d-x4) → 5376x3072 = 16.5MP, then JPEG/sRGB.
- Metadata: title ≤200 chars, ≤49 keywords, first ~10 weighted most;
  no artist names, real people, fictional characters, brands, or
  copyrighted works; keywords must be accurate to the image.

### Visual QC (image inspected via preview URL, 2026-11-26)

Reads as a high-contrast flat/poster illustration: near-black
silhouette desk with two laptops, detailed foliage in two planters,
window grid with saturated blue panes, warm floor reflections,
striped rug foreground. Weaknesses: furniture at right edge cropped
by the frame; office chair from the prompt not discernible (merged
into the black mass); small ambiguous bump on the desk surface;
partial dark bar at left edge. Style is consistent enough to read
as intentional flat design, but composition is rough for stock —
acceptable as a category/metadata test vehicle, marginal as a
polished product.

### Draft metadata (illustration category, v2)

- **Title:** Flat design illustration of a modern home office with
  laptops, plants and large window, remote work concept (109 chars)
- **Alt title:** Modern home office flat illustration, remote work
  and freelancing concept
- **Suggested category:** Business (alt: Lifestyle)
- **Keywords (ordered, 40):** remote work, home office, flat design,
  work from home, illustration, laptop, office interior, workspace,
  houseplant, desk, freelancer, digital nomad, silhouette, modern
  office, telecommuting, window, indoor plants, productivity, hybrid
  work, freelance, workplace, computer, technology, cozy, minimal,
  video call, online meeting, morning light, business, lifestyle,
  remote job, telework, interior, hardwood floor, contemporary,
  design, communication, corporate, job, ergonomic
- Deliberately omitted: "vector" (raster file — misleading), "cartoon"
  (style mismatch; spec's trending-cartoon note doesn't describe this
  asset), "generative AI" (not required, wastes keyword space).

### Decision: **keep as second product line — asset is pilot, not product**

Rationale: OPS-1078 already declared the omen sd lane illustration-tier;
a second line is the consequence of that verdict, not a new cost.
This specific asset is the metadata/category test vehicle — to be
submission-ready it still needs x4 upscale + JPEG/sRGB + the two gen-AI
checkboxes, and it remains marginal on composition. If Tony's visual QC
judges the silhouette reads as defect rather than style, discard the
ASSET but keep the product line — produce a purpose-prompted flat-design
render ("flat vector illustration style" in-prompt) instead of
salvaging a photo failure.
