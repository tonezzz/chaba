# place-report-empty-page — outcome

## What was wrong

`place-cape-sports-center-langebaan-259487` in `ada-cms-pages-kk` is a
title-only page (`# Cape Sports Center Langebaan` — no map, links, or
body). Root cause in `place_report.run()`: a bare `place=` ask (the kk
lane "ขอแผนที่ <place>" repro, no URL) goes through `_resolve`'s
name-only Nominatim search. On a miss it returns `name` set with
`coords` and `resolved_url` both empty — and the only publish gate was
`not name and not coords`, so it published an empty `meta.public` page.

## What changed

- `integrations/ada-pi/backend/tools.d/place_report.py` — new branch in
  `run()`: when resolution yields no coords AND no `resolved_url`, no
  page is published. Returns `{ok: false, unresolved: true, name,
  maps_url, error}` where `maps_url` is a
  `google.com/maps/search/?api=1&query=<name>` fallback the model sends
  in chat (or it asks the member for the place's maps link). A `url=`
  that expanded to a real maps link still publishes with no coords —
  that page carries a working link, not an empty shell. DECLARATION
  description updated to match.
- `integrations/ada-pi/backend/tool_guide.place_report.yml` — model
  guidance: `unresolved: true` means no page exists; send `maps_url`
  and/or ask for a maps link; never claim a page when `ok` is false.
- `tests/ada/test_place_report_drop.py` — 2 new tests (17 total):
  Nominatim-miss and Nominatim-down bare-name asks assert
  `pub_calls == []` plus the `maps_url` fallback.
- `integrations/ada-pi/README.md` — Drop 4 status updated: staged
  `place_report.py`/`tool_guide` are now AHEAD of the deployed ada-pi
  copies (manifest still byte-identical); unresolved contract
  documented.
- `docs/kb/lane-place-reports.md` — rule 6 added: "Unresolved = no
  page" as the standing truthfulness contract.
- `docs/ssot/jobs/ada/2026-10-13-place-report-empty-guard.yml` — job
  record with repro, deliverables, follow-ups.

## Result

`pytest tests/ada/test_place_report_drop.py` → **17 passed** (in a
worktree-local venv since system python lacks pytest/httpx; venv
removed after). Verify by re-running the same command with any python
that has `pytest httpx pyyaml`, or once deployed: ask kk lane
"ขอแผนที่ <obscure place>" with no URL → reply carries a Google Maps
search link, and no `place-*` doc is written to `ada-cms-pages-kk`.

## Not done (needs live-side action)

- **Deploy:** staged files are ahead of live ada-pi on idc03 ada-kk.
  Land via `cp` + ada-pi gates (`tool-lint`, pytest) + lane restart —
  a deploy step outside this worktree's mandate.
- **Cleanup:** the bare `place-cape-sports-center-langebaan-259487`
  page (and any title-only `place-*` siblings) still exists in
  `ada-cms-pages-kk` — delete or mark superseded on the live side.
