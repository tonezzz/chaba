```json
{
  "campaign_id": "AS-2026-11-05-REMOTE-WORK-001",
  "upload_candidate": {
    "asset_id": "comparison-d-x4-sharp60",
    "title": "Bright Modern Home Office and Workspace for Remote Work",
    "adobe_prompt": "A realistic commercial stock image of a bright modern home office prepared for remote work, closed or dark laptop screen turned away, clean desk, soft natural morning light, green indoor plant with sharp leaves, ample blank copy space on the left, landscape composition, professional interior design photography",
    "keywords": [
      "home office",
      "remote work",
      "workspace",
      "laptop",
      "desk",
      "bright",
      "modern",
      "office",
      "copy space",
      "morning light",
      "indoor plant",
      "interior design",
      "freelancer",
      "Scandinavian design",
      "clean",
      "minimalist",
      "professional",
      "commercial",
      "stock photo",
      "cozy",
      "houseplant",
      "daylight",
      "technology",
      "comfort",
      "lifestyle"
    ],
    "rationale": "The upscaled RealESRGAN-x4 sharp60 candidate represents the highest commercial stock resolution (5376x3072) and actively resolves the softness / photorealism concerns of the baseline Q8 model via a strong unsharp masking pass."
  },
  "asset_reuse": [
    {
      "asset_id": "remote-work-home-office-001",
      "decision": "hold",
      "reason": "Baseline comparison asset with blurry plant leaves, kept only for structural benchmarks.",
      "provenance": {
        "sha256": "8b9961f73d61dfbeaa05ea03ca0f884309d880c8feed6244dc27691721603624",
        "provider": null,
        "job_id": null,
        "source_ref": "remote-work-home-office-001",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-b-sharp-leaves",
      "decision": "remix",
      "reason": "Leaves are sharp but composition or overall color grading requires revision.",
      "provenance": {
        "sha256": "4d5694c0ee3a4249d2fa69cf48d36a7121ce7c4ce01a7f55ce1a0243e535535a",
        "provider": "kk-mac-sdxl",
        "job_id": null,
        "source_ref": "30-candidates/comparison-b-sharp-leaves/comparison-b-sharp-leaves.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-c-omen-sdxl",
      "decision": "reject",
      "reason": "Rejected for photorealism (reads as color paint); could be pivoted to separate illustration line.",
      "provenance": {
        "sha256": "905631838a88e177dac783b4c35ee75b5bead3db15274ec3261c3f5ce5c3750d",
        "provider": "tony-omen-sd-server",
        "job_id": "job_6aeea32e_00000001",
        "source_ref": "comparison-c-omen-sdxl",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-cf-flux-schnell",
      "decision": "remix",
      "reason": "Needs revision to correct the 1:1 aspect ratio to horizontal landscape format.",
      "provenance": {
        "sha256": "c2677dbac97ddbd2c24952f5c86c6bf6746d9a9991feb49c74868968534f63ae",
        "provider": "cf-workers-ai",
        "job_id": "@cf/black-forest-labs/flux-1-schnell",
        "source_ref": "render-005-cf-flux",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-omen-sdxl-q8",
      "decision": "remix",
      "reason": "Looks good but lacks high-frequency photorealistic details; upscaling and sharpening is required.",
      "provenance": {
        "sha256": "199027ffd31a2eff9c8cb04c88fa46e791125ad61c7066f4020615bd5fab6691",
        "provider": "omen-sd",
        "job_id": "job_6aeee1d0_00000000",
        "source_ref": "render-004-q8-experiment",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-wallfix",
      "decision": "remix",
      "reason": "Wall-corner fix succeeds mid-wall, but vertical objects look floating and need grounding contact shadows.",
      "provenance": {
        "sha256": "e67e1f6deeec9b3bb9dbddbd0109a1dd930a8559011ef3bb9fae51c16417a811",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "render-005-gemini-edit",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-x4",
      "decision": "hold",
      "reason": "Upscaled comparison variant; held pending Tony's final visual quality check.",
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
      "reason": "Moderate unsharp mask 40 upscale; held to compare artifacts vs sharp60 variant.",
      "provenance": {
        "sha256": "1ef079bb83c8f08af1fe0e039684a92469974a913b700539be61bfc32712c09e",
        "provider": "postprocess",
        "job_id": "local-ncnn",
        "source_ref": "30-candidates/comparison-d-x4-sharp40/comparison-d-x4-sharp40.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-x4-sharp60",
      "decision": "hold",
      "reason": "Selected upload candidate; held strictly pending visual validation from Tony.",
      "provenance": {
        "sha256": "b8b27a00c9f293f6458a75b2fb53d8629aa3e284da59784cfd60327c1b261697",
        "provider": "postprocess",
        "job_id": "local-ncnn",
        "source_ref": "30-candidates/comparison-d-x4-sharp60/comparison-d-x4-sharp60.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-g-omen-sdxl-q8-wallfix",
      "decision": "hold",
      "reason": "Structural experiment with wall corner fix; held pending visual review of seam lines.",
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
      "reason": "Brightness/relight and foliage sharpness worked, but composition still requires manual correction.",
      "provenance": {
        "sha256": "a127566c1ec6ce53a52909c95948291558de9ef5c7d3f906f501213dad39feab",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "render-006-gemini-relight",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix3-region",
      "decision": "remix",
      "reason": "Region-based edit successfully patched the corner, but requires final polish before upscale.",
      "provenance": {
        "sha256": "e519f5e538d890a1625dfc23b5151e7eb7b93eeb1f76d740b286c77c170a74d0",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "picker-20261108T025838Z",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix4-wheels",
      "decision": "hold",
      "reason": "Inpainted details on chair wheels need to be visually assessed; index is currently lacking preview.",
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
      "reason": "Local composited wheel inpainting requires visual evaluation and generation of a preview.",
      "provenance": {
        "sha256": "1e9d1ade19216f0998cbc3b29e64cbde4c7ad40db2541993daf548d6c6427431",
        "provider": "local-file",
        "job_id": "fix3-wheels-composited.png",
        "source_ref": "inpaint-wheels-omen-lightning-001",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-e-cf-inpaint-wheels",
      "decision": "hold",
      "reason": "CF-inpainted wheel composition must be verified on screen; preview currently missing.",
      "provenance": {
        "sha256": "90c09847320fe593525c1097106cf0ceeaec73d059923b96c4def08cd8affd1d",
        "provider": "local-file",
        "job_id": "tmp/inpaint-lane/fix3-wheels-cf-composited.png",
        "source_ref": "inpaint-cf-wheels-20261109",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-h-omen-sdxl-q8-cprompt",
      "decision": "hold",
      "reason": "Rerun on same-prompt comparison; held pending visual checking of photorealism band.",
      "provenance": {
        "sha256": "13ab4de2420197dd0ea19140343582aef0b51e102fecad50d760dfc5950fc9fb",
        "provider": "local-file",
        "job_id": "/tmp/ops1078-compare/comparison-h-omen-sdxl-q8-cprompt.png",
        "source_ref": "ops1078-q8-cprompt-rerun",
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
  "notes": "Campaign state is human_qc_pending with several inpaint visual checks awaiting Tony. Adhered strictly to read-only constraint; no filesystem mutations, external network requests, or status updates were performed."
}
```