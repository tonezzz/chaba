# ada-pi drop-in — trip_calendar tool

Staged for the **ada-pi repo** (`tonezzz/ada-pi`) — produced by the
chaba dispatch for card `ada-trip-calendar-pages` (2026-10-13). The
generator half (`scripts/ada/trip-calendar.py`) lives in THIS repo;
these files are the Ada-side surface.

## Install (ada-pi worktree)

1. `cp integrations/ada-pi/backend/tools.d/trip_calendar.py
   <ada-pi>/backend/tools.d/trip_calendar.py`
2. Merge `backend/tools.d/manifest.trip_calendar.yml`'s `trip_calendar:`
   block into `<ada-pi>/backend/tools.d/manifest.yml` under `tools:`.
   (Note: `conv_journal` is also missing a manifest entry on
   b776e81-era checkouts — add both while there.)
3. Append `backend/tool_guide.trip_calendar.yml` to
   `<ada-pi>/backend/tool_guide.yml`.
4. Tool profiles already updated in this repo —
   `docs/ssot/apps/ssot.apps.ada-persons.yml` adds `trip_calendar` to
   `persons.kk.tools.include`, `bench_profiles.kk-cms-only` and
   `kk-parity` (parity also gained the missing `page_snapshot` +
   `conv_journal` — it had drifted). Re-run
   `scripts/ada/render-tool-profiles.py` for `ada-kk.env` /
   `ada-kk-dev.env` on idc03.
5. Gates: `python3 scripts/tool-lint.py`, `pytest tests/ -x -q`; the
   generator needs `CHABA_REPO` to point at a checkout containing
   `scripts/ada/trip-calendar.py` (default `~/CascadeProjects/chaba`,
   correct on idc03) or `TRIP_CALENDAR` for an explicit path.

## Contract

- `trip_calendar(slug, start?, end?, title?, keywords?, public?, confirmed?)`
- Lane binding by `ADA_CMS_COLLECTION` — ada-cms-pages→tony,
  -kk→kk, -kk-dev→kk-dev. The tool can't write another lane's CMS.
- `public='yes'` requires `confirmed='yes'` (explicit-ask rule, same as
  `cms_publish_page`'s public flag).
- Returns `{ok, rollup, leaves, days, events, collection, span,
  view_url, public_url, errors}` — the model answers with the link.
