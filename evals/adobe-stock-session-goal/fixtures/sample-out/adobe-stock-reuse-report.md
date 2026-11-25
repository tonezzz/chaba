# Adobe Stock reuse QC — remote work home office

Goal `adobe-stock-reuse-qc-v1` · campaign idea `remote work home office` ·
campaign `AS-2026-11-05-REMOTE-WORK-001` (as returned by
`ada_adobe_stock_reuse`)

*Fixture output — synthetic shape example, not a real session result.*

## Report summary

`ada_adobe_stock_reuse(campaign_idea="remote work home office",
compact=false)` called once at 2026-11-25T09:30:00+07:00; report returned
3 candidate assets (fixture subset of the live index).

## Candidates

| asset_id | decision | preview_status | provider |
|---|---|---|---|
| comparison-c-omen-sdxl | reuse | available | tony-omen-sd-server |
| comparison-d-x4 | hold | available | postprocess |
| comparison-e-gemini-fix3-region | reuse | available | gemini-image |

## Missing previews

None — `missing_previews` is `[]` in this fixture. (Live runs must list
every asset_id the report returns without preview_url/thumbnail_url.)

## Open questions

- `comparison-d-x4` is an upscale of `comparison-d-omen-sdxl-q8` —
  confirm dedupe intent before reuse.
- Fixture subset note: live runs must cover every asset the report
  returns, not a sample.

## Policy

Read-only session: no cards created, nothing uploaded, generated,
licensed, or published. `mutations_performed` is empty; the
`no_mutation_receipt` in the JSON artifact is the attestation.
