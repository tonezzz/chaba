{
  "campaign_id": "AS-2026-11-05-REMOTE-WORK-001",
  "upload_candidate": {
    "asset_id": "comparison-e-gemini-fix3-region",
    "title": "Bright Modern Home Office for Remote Work - Corner Fixed",
    "adobe_prompt": "A realistic commercial stock image of a bright modern home office prepared for remote work, laptop screen turned away, clean desk with crisp sharply defined indoor plant leaves, soft natural morning light, ample blank copy space on the left, landscape composition, no logos, no brands, no readable text, no famous people, corrected wall-corner grounding with contact shadow",
    "keywords": [
      "home office",
      "remote work",
      "modern workspace",
      "natural light",
      "copy space",
      "laptop",
      "indoor plants",
      "clean desk",
      "commercial photography",
      "stock photo"
    ],
    "rationale": "This asset represents the most targeted revision: picker-driven region edit successfully fixed the wall-corner grounding issue (contact shadow/vertical floating) while retaining sharp plant leaves and good relight from prior Gemini iterations. It has preview metadata available and the QC note explicitly states 'Decision: revise (corner fixed)', indicating the specific defect was addressed. Best balance of photorealism fixes among assets with previews."
  },
  "asset_reuse": [
    {
      "asset_id": "remote-work-home-office-001",
      "decision": "hold",
      "reason": "Baseline kept for comparison only; plant leaves slightly blurry per QC; not final submission quality",
      "provenance": {
        "sha256": "8b9961f73d61dfbeaa05ea03ca0f884309d880c8feed6244dc27691721603624",
        "provider": "stabilityai/stable-diffusion-xl-base-1.0",
        "job_id": "",
        "source_ref": "baseline_asset_id",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-b-sharp-leaves",
      "decision": "remix",
      "reason": "QC decision 'revise' - crisp plant leaves achieved but needs further refinement before submission",
      "provenance": {
        "sha256": "4d5694c0ee3a4249d2fa69cf48d36a7121ce7c4ce01a7f55ce1a0243e535535a",
        "provider": "kk-mac-sdxl",
        "job_id": "render-002-comparison-b",
        "source_ref": "30-candidates/comparison-b-sharp-leaves/comparison-b-sharp-leaves.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-c-omen-sdxl",
      "decision": "reject",
      "reason": "QC decision 'reject_for_photorealism' - reads as color paint/illustration; belongs to different product line (illustration), not this photo campaign",
      "provenance": {
        "sha256": "905631838a88e177dac783b4c35ee75b5bead3db15274ec3261c3f5ce5c3750d",
        "provider": "tony-omen-sd-server",
        "job_id": "job_6aeea32e_00000001",
        "source_ref": "30-candidates/comparison-c-omen-sdxl/comparison-c-omen-sdxl.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-cf-flux-schnell",
      "decision": "remix",
      "reason": "QC decision 'revise' - needs revision before reuse; Flux Schnell variant at 1024x1024",
      "provenance": {
        "sha256": "c2677dbac97ddbd2c24952f5c86c6bf6746d9a9991feb49c74868968534f63ae",
        "provider": "cf-workers-ai",
        "job_id": "@cf/black-forest-labs/flux-1-schnell",
        "source_ref": "30-candidates/comparison-e-cf-flux-schnell/comparison-e-cf-flux-schnell.jpg",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-omen-sdxl-q8",
      "decision": "remix",
      "reason": "QC decision 'revise' - smooth but lacks photorealistic feel; upscale+sharpen pass in flight per notes",
      "provenance": {
        "sha256": "199027ffd31a2eff9c8cb04c88fa46e791125ad61c7066f4020615bd5fab6691",
        "provider": "omen-sd",
        "job_id": "job_6aeee1d0_00000000",
        "source_ref": "30-candidates/comparison-d-omen-sdxl-q8/comparison-d-omen-sdxl-q8.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-wallfix",
      "decision": "remix",
      "reason": "QC decision 'revise' - wall-corner fix works mid-wall but vertical floating needs contact shadow/grounding; overall darker",
      "provenance": {
        "sha256": "e67e1f6deeec9b3bb9dbddbd0109a1dd930a8559011ef3bb9fae51c16417a811",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "30-candidates/comparison-e-gemini-wallfix/comparison-e-gemini-wallfix.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-x4",
      "decision": "hold",
      "reason": "QC decision 'pending_visual_qc' - 4x Real-ESRGAN upscale of comparison-d-omen-sdxl-q8; awaiting Tony visual QC",
      "provenance": {
        "sha256": "5bf3881619178701c1c4b3f6d76b47355e5d9dec4cb3f77544d217a0eca409c5",
        "provider": "postprocess",
        "job_id": "local-ncnn",
        "source_ref": "30-candidates/comparison-d-x4/comparison-d-x4.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-d-x4-sharp40",
      "decision": "hold",
      "reason": "QC decision 'pending_visual_qc' - 4x upscale + unsharp40; awaiting Tony visual QC",
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
      "reason": "QC decision 'pending_visual_qc' - 4x upscale + unsharp60; awaiting Tony visual QC",
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
      "reason": "QC decision 'pending_visual_qc' - wallfix variant of omen-sdxl-q8; awaiting Tony visual QC",
      "provenance": {
        "sha256": "a46d9e58577f8c058540570f8779bcffbfaf38169f84fec4a33b1fcf63e2d5df",
        "provider": "omen-sd",
        "job_id": "job_6aeefe1a_00000001",
        "source_ref": "30-candidates/comparison-g-omen-sdxl-q8-wallfix/comparison-g-omen-sdxl-q8-wallfix.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix2",
      "decision": "remix",
      "reason": "QC decision 'revise' - brightness/relight worked, leaves sharp; needs further refinement before submission",
      "provenance": {
        "sha256": "a127566c1ec6ce53a52909c95948291558de9ef5c7d3f906f501213dad39feab",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "30-candidates/comparison-e-gemini-fix2/comparison-e-gemini-fix2.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix3-region",
      "decision": "remix",
      "reason": "QC decision 'revise (corner fixed)' - picker-driven region edit fixed corner; strongest revised candidate with preview",
      "provenance": {
        "sha256": "e519f5e538d890a1625dfc23b5151e7eb7b93eeb1f76d740b286c77c170a74d0",
        "provider": "gemini-image",
        "job_id": "gemini-2.5-flash-image",
        "source_ref": "30-candidates/comparison-e-gemini-fix3-region/comparison-e-gemini-fix3-region.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "available"
    },
    {
      "asset_id": "comparison-e-gemini-fix4-wheels",
      "decision": "hold",
      "reason": "QC decision 'pending_visual_qc' - wheels inpaint variant; no preview metadata; awaiting Tony visual QC",
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
      "reason": "QC decision 'pending_visual_qc' - wheels inpaint via omen lightning; no preview metadata; awaiting Tony visual QC",
      "provenance": {
        "sha256": "1e9d1ade19216f0998cbc3b29e64cbde4c7ad40db2541993daf548d6c6427431",
        "provider": "local-file",
        "job_id": "fix3-wheels-composited.png",
        "source_ref": "30-candidates/comparison-e-omen-sdxl-inpaint-wheels/fix3-wheels-composited.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-e-cf-inpaint-wheels",
      "decision": "hold",
      "reason": "QC decision 'pending_visual_qc' - wheels inpaint via CF; no preview metadata; awaiting Tony visual QC",
      "provenance": {
        "sha256": "90c09847320fe593525c1097106cf0ceeaec73d059923b96c4def08cd8affd1d",
        "provider": "local-file",
        "job_id": "tmp/inpaint-lane/fix3-wheels-cf-composited.png",
        "source_ref": "30-candidates/comparison-e-cf-inpaint-wheels/tmp/inpaint-lane/fix3-wheels-cf-composited.png",
        "campaign_id": "AS-2026-11-05-REMOTE-WORK-001"
      },
      "preview_status": "unavailable"
    },
    {
      "asset_id": "comparison-h-omen-sdxl-q8-cprompt",
      "decision": "hold",
      "reason": "QC decision 'pending_visual_qc' - same-prompt comparison for photorealism question (OPS-1078); Laplacian variance 1531; no preview metadata; awaiting Tony visual QC",
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
  "notes": "Upload candidate selected from assets with available previews and 'revise' QC decisions showing concrete fixes applied. comparison-e-gemini-fix3-region chosen for successful corner fix via picker-driven region edit while retaining sharp leaves and good relight. Five assets lack preview metadata (has_preview_url: false) — baseline and three wheels-inpaint variants plus the OPS-1078 comparison — reported explicitly as missing_previews. comparison-c-omen-sdxl rejected for photorealism (reads as illustration) per QC; noted as potential separate product line. All 'revise' assets mapped to 'remix'; 'pending_visual_qc' mapped to 'hold' awaiting Tony; baseline 'keep_for_comparison' mapped to 'hold'. No mutations, uploads, generation, or licensing performed."
}