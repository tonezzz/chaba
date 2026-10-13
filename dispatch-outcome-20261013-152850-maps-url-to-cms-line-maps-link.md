# dispatch outcome — maps-url-to-cms (kk lane)

**Card:** maps-url-to-cms-line-maps-link-resolved-c418f8 (KNB-0574)
**Branch:** dispatch/20261013-152850-maps-url-to-cms-line-maps-link
**Commit:** b100cee6d

## What was found

The ada-pi half was already built and deployed by the prior dispatch
on this card (earlier same-day session):

- `backend/tools.d/place_report.py` in ada-pi (`074c7a8` +
  `e24b14d` on `main`, pushed) — expands maps.app.goo.gl /
  google.com/maps links, resolves name+coords (Nominatim enrich, no
  key), publishes a `meta.public` markdown page via `cms_publish_page`,
  returns `public_url` for the LINE reply.
- Live on idc03 `ada-kk` since 15:26: `ADA_INCLUDED_TOOLS` ends
  `…,doc_read,place_report`; `ADA_CMS_PUBLIC_BASE=https://chaba.h3.gizmo-thailand.com/kk-ha/`
  hand-set; `ADA_CMS_COLLECTION=ada-cms-pages-kk`.
- End-to-end verified live: `cms-h3-publish.timer` on tony-dell already
  shipped real pages — `place-waterfall-safari-lodge-6fd9c6.html` and
  friends return HTTP 200 on `chaba.h3.gizmo-thailand.com/kk-ha/`, and
  LINE reply POSTs were 200 during the test window.

## What this session changed (chaba repo, this branch)

The chaba-side record was missing — the tool was deployed but not
staged, and the rendered tool profiles didn't know about it (next
`render-tool-profiles.py --apply` would have silently stripped
`place_report` from `ada-kk.env`). Committed:

- `integrations/ada-pi/backend/tools.d/place_report.py` — staged copy,
  byte-identical (sha256 `01f7eb4c…`) to idc03 deployed.
- `integrations/ada-pi/backend/tools.d/manifest.place_report.yml` +
  `tool_guide.place_report.yml` — fragments matching ada-pi `074c7a8`.
- `integrations/ada-pi/README.md` — Drop 4 section (status DEPLOYED,
  install-for-rebuild steps, contract, known gaps).
- `docs/ssot/apps/ssot.apps.ada-persons.yml` — `place_report` added to
  `persons.kk.tools.include`, `bench_profiles.kk-cms-only`, and
  `kk-parity`; comments record the hand-set `ADA_CMS_PUBLIC_BASE`.
- `tests/ada/test_place_report_drop.py` — 15 tests over the staged
  copy (pure helpers + `run()` e2e with fake httpx + fake
  `cms_publish_page`). All pass.
- `docs/ssot/jobs/ada/2026-10-13-maps-url-to-cms-place-report.yml` —
  job record (flow, deliverables, verify, gaps).

`node scripts/ssot-validate-all.mjs`: 2241 files, 0 errors.

## Gaps / follow-ups (also on the card)

1. **No dedup in the tool** — slug is `place-<name>-<sha1(name|coords)>`;
   the same place under different name spellings produced THREE
   `place-*jj-j-bistro*` pages in `ada-cms-pages-kk` on day one.
   `docs/kb/lane-place-reports.md` rule 5 wants cms_read-before-publish;
   neither tool nor tool_guide enforces it → needs a follow-up card
   (ada-pi side).
2. **ada-kk-dev.env** lacks `place_report` + `ADA_CMS_PUBLIC_BASE` —
   intentional for now; a kk-parity render adds the tool but the dev
   lane still needs the PUBLIC_BASE line hand-set or `public_url`
   derives to `surf-thailand.com/kk-dev-ha/` (not the h3 site).
3. `ada-pi` `_cms_public_base()` default still derives
   `surf-thailand.com/<tenant>-ha/` — wrong lane default for the
   chaba.h3 publish flow; every public lane needs the env override.
4. ada-pi `ssot.tool-surface.yml` `count_cap` comment is stale
   ("103 builtin + 9 tools.d" vs actual 37+14=51); cosmetic, cap not
   breached.

## How to verify

- `pytest tests/ada/test_place_report_drop.py` → 15 passed.
- `python3 scripts/ada/render-tool-profiles.py` → persons.kk rendered
  block ends `…,doc_read,place_report` — byte-matches live
  `ada-kk.env` on idc03.
- `curl -I https://chaba.h3.gizmo-thailand.com/kk-ha/place-waterfall-safari-lodge-6fd9c6.html`
  → 200.
- Live: send Kaewta a maps.app.goo.gl link in LINE → she calls
  place_report → reply carries the chaba.h3 link → page live within
  ~15min (publisher cadence).
