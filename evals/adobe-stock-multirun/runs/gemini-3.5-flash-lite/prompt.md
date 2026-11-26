# Adobe Stock campaign brief — read-only multirun eval

You are one arm of a bounded model comparison (card
`openchamber-multirun-adobe-stock-prompts`). You have NO tools: everything
you need is inline below. Do not attempt file, shell, web, board, or MCP
access — there is nothing to call, and any attempted mutation fails the
run.

## Task

Given the frozen Adobe Stock campaign state for campaign
`AS-2026-11-05-REMOTE-WORK-001` ("Remote work home office"), produce a
campaign recommendation covering:

1. **Upload candidate** — pick the single best asset to prepare for
   Adobe Stock submission and write its title, refined Adobe prompt,
   and keywords.
2. **Asset reuse** — for EVERY asset in `assets`, a reuse decision
   (`reuse`, `remix`, `reject`, or `hold`) with a one-line reason and
   its provenance block copied verbatim from the input record.
3. **Missing previews** — list every asset_id that lacks preview
   metadata (`has_preview_url` false) so the index gap is explicit.
4. **Policy** — confirm nothing was uploaded, generated, licensed, or
   mutated.

Respect the campaign's actual state: the canonical human verdict per
asset is `qc_decision` (`keep_for_comparison`, `revise`,
`reject_for_photorealism`, `pending_visual_qc`), with detail in
`qc_notes` and `manifest_qc_decision` — honor them. A
`reject_for_photorealism` verdict must not be `reuse`d for this photo
campaign (a rejected asset may be `hold`/`remix`/`reject`, or noted as
belonging to a different product line); `revise` means `remix`/`hold`,
not silent `reuse`; `pending_visual_qc` means `hold`/`remix` pending
Tony. Assets absent from the run index have no preview metadata — that
is a fact to report, not something to paper over. Do not invent
assets, sha256 values, providers, or URLs.

## Output contract — emit EXACTLY ONE JSON object as your final message

No prose before or after, no markdown fence required (a fence is
accepted). Required shape:

```json
{
  "campaign_id": "AS-2026-11-05-REMOTE-WORK-001",
  "upload_candidate": {
    "asset_id": "<one asset_id from assets[]>",
    "title": "<string>",
    "adobe_prompt": "<string>",
    "keywords": ["<string>", "..."],
    "rationale": "<string>"
  },
  "asset_reuse": [
    {
      "asset_id": "<asset_id>",
      "decision": "reuse|remix|reject|hold",
      "reason": "<string>",
      "provenance": {
        "sha256": "<copy from input>",
        "provider": "<copy from input>",
        "job_id": "<copy from input>",
        "source_ref": "<copy from input or campaign path>",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available|thumbnail-only|unavailable|unknown"
    }
  ],
  "missing_previews": ["<asset_id>", "..."],
  "policy": {
    "mutations_performed": [],
    "adobe_upload": false,
    "generation_requested": false,
    "licensing_requested": false
  },
  "notes": "<string>"
}
```

`asset_reuse` must contain one entry per asset in `assets` (16 entries).
`preview_status` must be `unavailable` for every asset with
`has_preview_url: false`. `mutations_performed` must be an empty array.

## Frozen campaign input (identical for every arm)

```json
{
 "campaign_id": "AS-2026-11-05-REMOTE-WORK-001",
 "title": "Remote work home office",
 "status": "human_qc_pending",
 "current_stage": "40-qc-review",
 "snapshot_at": "2026-11-25T07:18Z (campaign-status receipt)",
 "pending_decisions": [
  "Tony: visual QC wheels repair \u2014 fix3-region vs gemini-fix4-wheels vs cf-inpaint-wheels vs omen-sdxl-inpaint-wheels (30-candidates/)",
  "Tony: QC comparison-g-omen-sdxl-q8-wallfix + comparison-d-x4 variants"
 ],
 "baseline_asset_id": "remote-work-home-office-001",
 "qc_outcomes": {
  "candidate_qc": "revise",
  "revision_qc": "reject_for_photorealism"
 },
 "baseline_prompt": "A realistic commercial stock image of a bright modern home office prepared for remote work, laptop screen turned away, clean desk, soft natural morning light, ample blank copy space on the left, landscape composition, no logos, no brands, no readable text, no famous people.",
 "baseline_negative_prompt": "logo, brand, watermark, readable text, distorted anatomy, duplicate objects",
 "assets": [
  {
   "asset_id": "remote-work-home-office-001",
   "in_run_index": false,
   "sha256": "8b9961f73d61dfbeaa05ea03ca0f884309d880c8feed6244dc27691721603624",
   "bytes": 697306,
   "has_preview_url": false,
   "has_thumbnail_url": false,
   "render_prompt": "A realistic commercial stock image of a bright modern home office prepared for remote work, laptop screen turned away, clean desk, soft natural morning light, ample blank copy space on the left, landscape composition, no logos, no brands, no readable text, no famous people.",
   "negative_prompt": "logo, brand, watermark, readable text, distorted anatomy, duplicate objects",
   "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
   "runtime": "diffusers-mps",
   "manifest_status": "kept_for_comparison",
   "manifest_qc_decision": "keep_for_comparison",
   "qc_notes": [
    "Decision: **keep for comparison**",
    "Note: plant leaves are slightly blurry. Keep this asset as the baseline comparison; do not treat it as the final Adobe Stock submission yet."
   ],
   "qc_decision": "keep_for_comparison"
  },
  {
   "asset_id": "comparison-b-sharp-leaves",
   "in_run_index": true,
   "provider": "kk-mac-sdxl",
   "sha256": "4d5694c0ee3a4249d2fa69cf48d36a7121ce7c4ce01a7f55ce1a0243e535535a",
   "bytes": 689964,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-b-sharp-leaves.png",
   "status": "candidate-qc-pending",
   "render_prompt": "A realistic commercial stock image of a bright modern home office prepared for remote work, with crisp sharply defined indoor plant leaves, a closed or dark laptop screen, clean desk, soft natural morning light, ample blank copy space on the left, landscape composition, no logos, no brands, no readable text, no famous people, avoid shallow-focus blur on the plant.",
   "negative_prompt": "logo, brand, watermark, readable text, distorted hands, distorted fingers, celebrity likeness, shallow-focus blur on plant leaves",
   "model": {
    "dir_name": "sdxl-base-1.0",
    "id": "stabilityai/stable-diffusion-xl-base-1.0",
    "revision": "462165984030d82259a11f4367a4eed129e94a7b",
    "runtime": "diffusers-mps"
   },
   "runtime": {
    "device": "mps:0",
    "diffusers_version": "0.42.1",
    "load_seconds": 12.014,
    "model_dir": "/Users/kkkakk/.local/share/kk-mac-image-renderer/models/sdxl-base-1.0",
    "render_seconds": 16.234,
    "torch_version": "2.15.0",
    "total_seconds": 28.277
   },
   "pack": "kk-mac-image-render-poc",
   "request_id": "render-002-comparison-b",
   "manifest_status": "done",
   "qc_notes": [
    "File: `30-candidates/comparison-b-sharp-leaves/comparison-b-sharp-leaves.png`",
    "Manifest: `30-candidates/comparison-b-sharp-leaves/comparison-b-sharp-leaves.manifest.json`",
    "sha256: `4d5694c0ee3a4249d2fa69cf48d36a7121ce7c4ce01a7f55ce1a0243e535535a`",
    "Decision: **revise**"
   ],
   "qc_decision": "revise"
  },
  {
   "asset_id": "comparison-c-omen-sdxl",
   "in_run_index": true,
   "provider": "tony-omen-sd-server",
   "job_id": "job_6aeea32e_00000001",
   "sha256": "905631838a88e177dac783b4c35ee75b5bead3db15274ec3261c3f5ce5c3750d",
   "dimensions": "1344x768",
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-c-omen-sdxl.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T05:15:11+00:00",
   "model": "sdxl-lightning-4step.q4_0.gguf",
   "endpoint": "http://100.75.102.88:8399/sdcpp/v1/img_gen",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "The photorealism rejection (\"reads as color paint\") is a **category",
    "### Decision: **keep as second product line \u2014 pending Tony visual QC**",
    "that rejected it for photo. If it passes visual QC as illustration, file"
   ],
   "qc_decision": "reject_for_photorealism"
  },
  {
   "asset_id": "comparison-e-cf-flux-schnell",
   "in_run_index": true,
   "provider": "cf-workers-ai",
   "job_id": "@cf/black-forest-labs/flux-1-schnell",
   "sha256": "c2677dbac97ddbd2c24952f5c86c6bf6746d9a9991feb49c74868968534f63ae",
   "dimensions": "1024x1024",
   "bytes": 457528,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-e-cf-flux-schnell.jpg",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T10:24:41.139711+00:00",
   "request_id": "render-005-cf-flux",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_decision": "revise"
  },
  {
   "asset_id": "comparison-d-omen-sdxl-q8",
   "in_run_index": true,
   "provider": "omen-sd",
   "job_id": "job_6aeee1d0_00000000",
   "sha256": "199027ffd31a2eff9c8cb04c88fa46e791125ad61c7066f4020615bd5fab6691",
   "dimensions": "1344x768",
   "bytes": 1878962,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-d-omen-sdxl-q8.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T11:10:10.529708+00:00",
   "request_id": "render-004-q8-experiment",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "- SHA-256: `199027ffd31a2eff9c8cb04c88fa46e791125ad61c7066f4020615bd5fab6691`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required.",
    "**Decision: revise.** \"Look smooth and good, but doesn't feel like",
    "photorealistic. Maybe more sharpen.\" Upscale + sharpen pass in flight"
   ],
   "qc_decision": "revise"
  },
  {
   "asset_id": "comparison-e-gemini-wallfix",
   "in_run_index": true,
   "provider": "gemini-image",
   "job_id": "gemini-2.5-flash-image",
   "sha256": "e67e1f6deeec9b3bb9dbddbd0109a1dd930a8559011ef3bb9fae51c16417a811",
   "dimensions": "1024x1024",
   "bytes": 1767675,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-e-gemini-wallfix.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T12:19:07.681816+00:00",
   "request_id": "render-005-gemini-edit",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "- SHA-256: `e67e1f6deeec9b3bb9dbddbd0109a1dd930a8559011ef3bb9fae51c16417a811`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required.",
    "**Decision: revise.** Wall-corner fix works mid-wall, but the vertical",
    "floating (needs contact shadow/grounding). Overall image reads darker"
   ],
   "qc_decision": "revise"
  },
  {
   "asset_id": "comparison-d-x4",
   "in_run_index": true,
   "provider": "postprocess",
   "job_id": "local-ncnn",
   "sha256": "5bf3881619178701c1c4b3f6d76b47355e5d9dec4cb3f77544d217a0eca409c5",
   "dimensions": "5376x3072",
   "bytes": 25297085,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-d-x4.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T12:23:57.154681+00:00",
   "request_id": "postprocess-realesrgan-x4plus-x4",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "derived_from": "comparison-d-omen-sdxl-q8",
   "qc_notes": [
    "- SHA-256: `5bf3881619178701c1c4b3f6d76b47355e5d9dec4cb3f77544d217a0eca409c5`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required."
   ],
   "qc_decision": "pending_visual_qc"
  },
  {
   "asset_id": "comparison-d-x4-sharp40",
   "in_run_index": true,
   "provider": "postprocess",
   "job_id": "local-ncnn",
   "sha256": "1ef079bb83c8f08af1fe0e039684a92469974a913b700539be61bfc32712c09e",
   "dimensions": "5376x3072",
   "bytes": 21095328,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-d-x4-sharp40.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T12:24:23.887046+00:00",
   "request_id": "postprocess-realesrgan-x4plus-x4+unsharp40",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "derived_from": "comparison-d-omen-sdxl-q8",
   "qc_notes": [
    "- File: `30-candidates/comparison-d-x4-sharp40/comparison-d-x4-sharp40.png` (5376x3072, 21095328 bytes)",
    "- SHA-256: `1ef079bb83c8f08af1fe0e039684a92469974a913b700539be61bfc32712c09e`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required."
   ],
   "qc_decision": "pending_visual_qc"
  },
  {
   "asset_id": "comparison-d-x4-sharp60",
   "in_run_index": true,
   "provider": "postprocess",
   "job_id": "local-ncnn",
   "sha256": "b8b27a00c9f293f6458a75b2fb53d8629aa3e284da59784cfd60327c1b261697",
   "dimensions": "5376x3072",
   "bytes": 22417918,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-d-x4-sharp60.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T12:24:50.995772+00:00",
   "request_id": "postprocess-realesrgan-x4plus-x4+unsharp60",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "derived_from": "comparison-d-omen-sdxl-q8",
   "qc_notes": [
    "- File: `30-candidates/comparison-d-x4-sharp60/comparison-d-x4-sharp60.png` (5376x3072, 22417918 bytes)",
    "- SHA-256: `b8b27a00c9f293f6458a75b2fb53d8629aa3e284da59784cfd60327c1b261697`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required."
   ],
   "qc_decision": "pending_visual_qc"
  },
  {
   "asset_id": "comparison-g-omen-sdxl-q8-wallfix",
   "in_run_index": true,
   "provider": "omen-sd",
   "job_id": "job_6aeefe1a_00000001",
   "sha256": "a46d9e58577f8c058540570f8779bcffbfaf38169f84fec4a33b1fcf63e2d5df",
   "dimensions": "1344x768",
   "bytes": 1760772,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-g-omen-sdxl-q8-wallfix.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-07T13:15:12.541397+00:00",
   "request_id": "render-004-wallfix",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "- SHA-256: `a46d9e58577f8c058540570f8779bcffbfaf38169f84fec4a33b1fcf63e2d5df`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required."
   ],
   "qc_decision": "pending_visual_qc"
  },
  {
   "asset_id": "comparison-e-gemini-fix2",
   "in_run_index": true,
   "provider": "gemini-image",
   "job_id": "gemini-2.5-flash-image",
   "sha256": "a127566c1ec6ce53a52909c95948291558de9ef5c7d3f906f501213dad39feab",
   "dimensions": "1024x1024",
   "bytes": 1829666,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-e-gemini-fix2.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-08T00:37:55.776707+00:00",
   "request_id": "render-006-gemini-relight",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "- SHA-256: `a127566c1ec6ce53a52909c95948291558de9ef5c7d3f906f501213dad39feab`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required.",
    "**Decision: revise.** Brightness/relight worked \u2014 leaves sharp. But the"
   ],
   "qc_decision": "revise"
  },
  {
   "asset_id": "comparison-e-gemini-fix3-region",
   "in_run_index": true,
   "provider": "gemini-image",
   "job_id": "gemini-2.5-flash-image",
   "sha256": "e519f5e538d890a1625dfc23b5151e7eb7b93eeb1f76d740b286c77c170a74d0",
   "dimensions": "1024x1024",
   "bytes": 1903022,
   "has_preview_url": true,
   "has_thumbnail_url": true,
   "preview_url": "https://157.85.102.125.sslip.io/relay-img/arch/renders/adobe-as-2026-11-05-remote-work-001-comparison-e-gemini-fix3-region.png",
   "status": "candidate-qc-pending",
   "landed_at": "2026-11-08T02:59:19.166201+00:00",
   "request_id": "picker-20261108T025838Z",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "- SHA-256: `e519f5e538d890a1625dfc23b5151e7eb7b93eeb1f76d740b286c77c170a74d0`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required.",
    "**Decision: revise (corner fixed).** Picker-driven region edit"
   ],
   "qc_decision": "revise"
  },
  {
   "asset_id": "comparison-e-gemini-fix4-wheels",
   "in_run_index": false,
   "provider": "gemini-image",
   "job_id": "gemini-2.5-flash-image",
   "sha256": "0dc1094c836ee43ad4dd650126c52dc6bd460eb00192d89e06b33c26f5da684a",
   "dimensions": "1024x1024",
   "bytes": 1955633,
   "has_preview_url": false,
   "has_thumbnail_url": false,
   "landed_at": "2026-11-08T05:48:08.710462+00:00",
   "request_id": "inpaint-wheels-gemini-001",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_decision": "pending_visual_qc"
  },
  {
   "asset_id": "comparison-e-omen-sdxl-inpaint-wheels",
   "in_run_index": false,
   "provider": "local-file",
   "job_id": "fix3-wheels-composited.png",
   "sha256": "1e9d1ade19216f0998cbc3b29e64cbde4c7ad40db2541993daf548d6c6427431",
   "dimensions": "1024x1024",
   "bytes": 1384527,
   "has_preview_url": false,
   "has_thumbnail_url": false,
   "landed_at": "2026-11-08T06:29:20.426006+00:00",
   "request_id": "inpaint-wheels-omen-lightning-001",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_decision": "pending_visual_qc"
  },
  {
   "asset_id": "comparison-e-cf-inpaint-wheels",
   "in_run_index": false,
   "provider": "local-file",
   "job_id": "tmp/inpaint-lane/fix3-wheels-cf-composited.png",
   "sha256": "90c09847320fe593525c1097106cf0ceeaec73d059923b96c4def08cd8affd1d",
   "dimensions": "1024x1024",
   "bytes": 1379709,
   "has_preview_url": false,
   "has_thumbnail_url": false,
   "landed_at": "2026-11-09T02:10:28.647976+00:00",
   "request_id": "inpaint-cf-wheels-20261109",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "- SHA-256: `90c09847320fe593525c1097106cf0ceeaec73d059923b96c4def08cd8affd1d`",
    "- Job: `tmp/inpaint-lane/fix3-wheels-cf-composited.png`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required."
   ],
   "qc_decision": "pending_visual_qc"
  },
  {
   "asset_id": "comparison-h-omen-sdxl-q8-cprompt",
   "in_run_index": false,
   "provider": "local-file",
   "job_id": "/tmp/ops1078-compare/comparison-h-omen-sdxl-q8-cprompt.png",
   "sha256": "13ab4de2420197dd0ea19140343582aef0b51e102fecad50d760dfc5950fc9fb",
   "dimensions": "1344x768",
   "bytes": 1975532,
   "has_preview_url": false,
   "has_thumbnail_url": false,
   "landed_at": "2026-11-25T02:35:34.803838+00:00",
   "request_id": "ops1078-q8-cprompt-rerun",
   "campaign": "AS-2026-11-05-REMOTE-WORK-001",
   "qc_notes": [
    "- SHA-256: `13ab4de2420197dd0ea19140343582aef0b51e102fecad50d760dfc5950fc9fb`",
    "QC checklist vs prior candidates: sharpness, artifacts, composition/copy space, commercial usefulness.",
    "Decision: keep / reject / revise \u2014 Tony visual QC required.",
    "Same-prompt comparison set for the photorealism question (OPS-1078):",
    "Laplacian-variance sharpness proxy: C 1218 / D 1670 / H 1531 \u2014 Q8 holds",
    "good, but doesn't feel photorealistic\" \u2014 H is the same model class;",
    "expect the same band. Decision: keep / reject / revise \u2014 Tony visual",
    "QC required; photoreal lane stays kk-mac/gemini/CF."
   ],
   "qc_decision": "pending_visual_qc"
  }
 ],
 "policy": {
  "adobe_upload": false,
  "note": "read-only analysis; no upload, generation, licensing, or card mutation is permitted"
 }
}
```
