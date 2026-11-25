# Multi-run comparison contract — AS-2026-11-05-REMOTE-WORK-001

Card: OPS-1039 (openchamber-multirun-adobe-stock-prompts)

## Shared input

Every lane receives the identical `render-request.json`:

```json
{
  "session_id": "AS-2026-11-05-REMOTE-WORK-001",
  "request_id": "render-004-multirun",
  "prompt": "<approved prompt>",
  "negative_prompt": "<approved negative>",
  "aspect": "16:9",
  "count": 1,
  "human_confirmed": true,
  "adobe_upload": false
}
```

## Lane profiles

| profile | host/lane | model | tier | status |
|---|---|---|---|---|
| kk-mac-sdxl | KK-Mac Nest pack | SDXL base 20-step | photo | staged, host offline |
| omen-sd-server | tony-omen :8399 | sdxl-lightning-4step Q4_0 | illustration | live (slow) |
| omen-sdxl-full | tony-omen :8399 | sdxl-base Q6/Q8 (OPS-1078) | photo? | experiment pending |
| gemini-image | LiteLLM image class | gemini-3.1-flash-image | photo+edit | blocked: credits |

## Per-run record (comparison-report.json)

```json
{
  "request_id": "render-004-multirun",
  "runs": [{
    "lane": "kk-mac-sdxl", "job_id": "...", "artifact": "...",
    "sha256": "...", "dimensions": "WxH", "bytes": 0,
    "wall_seconds": 0, "cost_usd": 0,
    "scores": {"sharpness": 0-5, "artifacts": 0-5,
               "prompt_adherence": 0-5, "copy_space": 0-5,
               "photorealism": 0-5},
    "verifier": "pass|fail", "qc_status": "pending"
  }],
  "recommended_lane": "...", "decided_by": "tony", "at": "..."
}
```

## Rules

- Identical prompt/negative/aspect/count across lanes; only provider differs.
- Each run lands PNG + manifest in 30-generated-raw/ with sha256.
- Scoring is human (Tony) + optional automated sharpness metric; verifier
  checks artifact integrity only, never aesthetics.
- No lane auto-retries; failed runs recorded, not hidden.
- adobe_upload stays false; manual submission only.
