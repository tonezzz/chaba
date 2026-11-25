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
{{INPUT_JSON}}
```
