```json
{
  "campaign_id": "AS-2026-11-05-REMOTE-WORK-001",
  "upload_candidate": {
    "asset_id": "remote-work-home-office-001",
    "title": "Bright Modern Home Office with Laptop and Natural Light",
    "adobe_prompt": "A realistic commercial stock image of a bright modern home office prepared for remote work, laptop screen turned away, clean desk, soft natural morning light, ample blank copy space on the left, landscape composition, no logos, no brands, no readable text, no famous people.",
    "keywords": [
      "home office",
      "remote work",
      "workspace",
      "desk",
      "laptop",
      "modern",
      "bright",
      "natural light",
      "interior",
      "copyspace",
      "work from home",
      "business",
      "professional",
      "minimalist",
      "empty desk"
    ],
    "rationale": "Although plant leaves are noted as slightly blurry in the baseline notes, remote-work-home-office-001 serves as the primary baseline comparison asset for the campaign. As no other candidate has cleared final human QC approval for immediate submission (the campaign status is human_qc_pending with pending visual QC wheels repair and post-processing comparisons), this baseline asset represents the core prompt intent and is selected as the representative upload candidate pending final polish."
  },
  "asset_reuse": [
    {
      "asset_id": "remote-work-home-office-001",
      "decision": "reuse",
      "reason": "Baseline comparison asset embodying core prompt intent.",
      "provenance": {
        "sha256": "8b9961f73d61dfbeaa05ea03ca0f884309d880c8feed6244dc27691721603624",
        "provider": "stabilityai/stable-diffusion-xl-base-1.0",
        "job_id": "baseline-generation",
        "source_ref": "baseline_asset_id",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-b-sharp-leaves",
      "decision": "remix",
      "reason": "Revise verdict; plant leaves sharpened but requires further alignment.",
      "provenance": {
        "sha256": "4d5694c0ee3a4249d2fa69cf48d36a7121ce7c4ce01a7f55ce1a0243e535535a",
        "provider": "kk-mac-sdxl",
        "job_id": "render-002-comparison-b",
        "source_ref": "kk-mac-sdxl",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-c-omen-sdxl",
      "decision": "reject",
      "reason": "Rejected for photorealism ('reads as color paint'); reserved as alternative product line pending visual QC.",
      "provenance": {
        "sha256": "905631838a88e177dac783b4c35ee75b5bead3db15274ec3261c3f5ce5c3750d",
        "provider": "tony-omen-sd-server",
        "job_id": "job_6aeea32e_00000001",
        "source_ref": "http://100.75.102.88:8399/sdcpp/v1/img_gen",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-cf-flux-schnell",
      "decision": "remix",
      "reason": "Revise verdict; Flux schnell variant for commercial comparison.",
      "provenance": {
        "sha256": "c2677dbac97ddbd2c24952f5c86c6bf6746d9a9991feb49c74868968534f63ae",
        "provider": "cf-workers-ai",
        "job_id": "@cf/black-forest-labs/flux-1-schnell",
        "source_ref": "cf-workers-ai",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-omen-sdxl-q8",
      "decision": "remix",
      "reason": "Revise verdict; smooth but requires sharpen pass.",
      "provenance": {
        "sha256": "199027ffd31a2eff9c8cb04c88fa46e791125ad61c7066f4020615bd5fab6691",
        "provider": "omen-sd",
        "job_id": "job_6aeee1d0_00000000",
        "source_ref": "omen-sd",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-wallfix",
      "decision": "remix",
      "reason": "Revise verdict; wall-corner fix works mid-wall but lacks contact shadow/grounding.",
      "provenance": {
        "sha256": "e67e1f6deeec9b3bb9dbddbd0109a1dd930a8559011ef3bb9fae51c16417a811",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "gemini-image",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-x4",
      "decision": "hold",
      "reason": "Pending visual QC by Tony.",
      "provenance": {
        "sha256": "5bf3881619178701c1c4b3f6d76b47355e5d9dec4cb3f77544d217a0eca409c5",
        "provider": "postprocess",
        "job_id": "local-ncnn",
        "source_ref": "postprocess-realesrgan-x4plus-x4",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-x4-sharp40",
      "decision": "hold",
      "reason": "Pending visual QC by Tony.",
      "provenance": {
        "sha256": "1ef079bb83c8f08af1fe0e039684a92469974a913b700539be61bfc32712c09e",
        "provider": "postprocess",
        "job_id": "local-ncnn",
        "source_ref": "postprocess-realesrgan-x4plus-x4+unsharp40",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-x4-sharp60",
      "decision": "hold",
      "reason": "Pending visual QC by Tony.",
      "provenance": {
        "sha256": "b8b27a00c9f293f6458a75b2fb53d8629aa3e284da59784cfd60327c1b261697",
        "provider": "postprocess",
        "job_id": "local-ncnn",
        "source_ref": "postprocess-realesrgan-x4plus-x4+unsharp60",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-g-omen-sdxl-q8-wallfix",
      "decision": "hold",
      "reason": "Pending visual QC by Tony.",
      "provenance": {
        "sha256": "a46d9e58577f8c058540570f8779bcffbfaf38169f84fec4a33b1fcf63e2d5df",
        "provider": "omen-sd",
        "job_id": "job_6aeefe1a_00000001",
        "source_ref": "render-004-wallfix",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix2",
      "decision": "remix",
      "reason": "Revise verdict; brightness/relight worked but requires further adjustment.",
      "provenance": {
        "sha256": "a127566c1ec6ce53a52909c95948291558de9ef5c7d3f906f501213dad39feab",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "gemini-image",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix3-region",
      "decision": "remix",
      "reason": "Revise verdict; corner fixed via picker-driven region edit.",
      "provenance": {
        "sha256": "e519f5e538d890a1625dfc23b5151e7eb7b93eeb1f76d740b286c77c170a74d0",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "gemini-image",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix4-wheels",
      "decision": "hold",
      "reason": "Pending visual QC by Tony (wheels repair).",
      "provenance": {
        "sha256": "0dc1094c836ee43ad4dd650126c52dc6bd460eb00192d89e06b33c26f5da684a",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "inpaint-wheels-gemini-001",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-e-omen-sdxl-inpaint-wheels",
      "decision": "hold",
      "reason": "Pending visual QC by Tony (wheels repair).",
      "provenance": {
        "sha256": "1e9d1ade19216f0998cbc3b29e64cbde4c7ad40db2541993daf548d6c6427431",
        "provider": "local-file",
        "job_id": "fix3-wheels-composited.png",
        "source_ref": "fix3-wheels-composited.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-e-cf-inpaint-wheels",
      "decision": "hold",
      "reason": "Pending visual QC by Tony (wheels repair).",
      "provenance": {
        "sha256": "90c09847320fe593525c1097106cf0ceeaec73d059923b96c4def08cd8affd1d",
        "provider": "local-file",
        "job_id": "tmp/inpaint-lane/fix3-wheels-cf-composited.png",
        "source_ref": "tmp/inpaint-lane/fix3-wheels-cf-composited.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-h-omen-sdxl-q8-cprompt",
      "decision": "hold",
      "reason": "Pending visual QC by Tony (OPS-1078 comparison).",
      "provenance": {
        "sha256": "13ab4de2420197dd0ea19140343582aef0b51e102fecad50d760dfc5950fc9fb",
        "provider": "local-file",
        "job_id": "/tmp/ops1078-compare/comparison-h-omen-sdxl-q8-cprompt.png",
        "source_ref": "/tmp/ops1078-compare/comparison-h-omen-sdxl-q8-cprompt.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    }
  ],
  "missing_previews": [
    "remote-work-home-office-001",
    "comparison-e-gemini-fix4-wheels",
    "comparison-e-omen-sdxl-inpaint-wheels",
    "comparison-e-cf-inpaint-wheels",
    "comparison-h-omen-sdxl-q8-cprompt"
  ],
  "policy": {
    "mutations_performed": [],
    "adobe_upload": false,
    "generation_requested": false,
    "licensing_requested": false
  },
  "notes": "Read-only evaluation completed successfully. All 16 assets evaluated according to their official qc_decision and preview status. Missing previews explicitly logged."
}
```