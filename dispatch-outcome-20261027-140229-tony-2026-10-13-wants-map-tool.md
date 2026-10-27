# Dispatch outcome — map-embed-tool (2026-10-27)

## What was built

Staged **ada-voice drop 17 — `map_embed`** in
`integrations/ada-voice/` (commit `f9d12afbe` on the dispatch branch).
The tool composes a POI/route map and returns CMS-ready snippets; the
model hands `markdown` to `cms_publish_page`/`cms_edit` or sends the
link in chat. Files:

- `backend/tools.d/map_embed.py` — the tool (DECLARATION + async run).
- `backend/tools.d/manifest.map_embed.yml` — manifest fragment
  (read policy, secondary_allowed, 60s).
- `backend/tool_guide.map_embed.yml` — tool_guide fragment.
- `tests/scenarios-live/map_embed.yaml` — smoke scenario (tool-lint
  requires scenario coverage for new tools).
- `docs/ssot/ssot.tool-surface.map_embed.patch` — `count_cap`
  112→113 ratchet bump; **verified `git apply --check` clean against
  the local ada-voice checkout** (main @ `59562cf`).
- `integrations/ada-voice/README.md` — drop 17 entry + install steps.
- `docs/ssot/apps/ssot.apps.ada-persons.yml` — `map_embed` added to
  `persons.tony.tools.include` and the `kk-cms-only` bench profile.
  persons.kk / kk-parity deliberately skip it (that lane has no cms_*
  writers; adding later is one line each).

## Behavior

- `kind=interactive` → Google Maps Embed API iframe (directions /
  place / chained-directions / view modes). Several places with no
  route chain into a directions map — the only way the embed API shows
  all pins (flagged in `warnings`). Needs `GOOGLE_MAPS_API_KEY`; the
  no-key return is honest `ok:false` + `needs_key` + `open_url` +
  `static_fallback`, never a dead iframe.
- `kind=static` → frozen map image. With the key: Maps Static API
  lettered markers + Routes API road-route polyline (straight-line
  fallback flagged; also returns `distance_km`/`duration_min`).
  Without the key: OpenStreetMap staticmap multi-pin image, name-only
  entries geocoded via Nominatim, no route line (flagged).
- `open_url` always returned — a keyless maps/dir or maps/search link
  that opens the same live map in Google Maps.

## Rendering reality check (verified in-repo renderers)

- Tailnet `apps/cms-render` (python-markdown) renders `![img]` and
  passes raw `<iframe>` HTML — both kinds work on the internal surface.
- Public `cms-publish-site.py` escapes all HTML and lacks an image
  inline rule — on meta.public pages a static image degrades to a link
  and an iframe to text; `open_url` is the durable public-facing map.
  Noted in the tool's `note` field and tool_guide.

## Result / verification

- `pytest tests/ada/test_map_embed_drop.py` — **21 passed** (uv venv:
  httpx, pytest, pyyaml; system python lacks them).
- All YAML fragments + persons.yml parse; commit-hook SSOT validation
  passed.
- Board: progress comment posted; **request raised** for the
  `GOOGLE_MAPS_API_KEY` gate (reuse the tony-dell gev key if its GCP
  project has Embed+Static+Routes APIs enabled vs a new key for the
  ada env on idc03). Tool ships useful without it — only interactive
  iframes, Google basemaps and road polylines are key-gated.

## Not done / next steps

- Not deployed (dispatch scope): install steps live in
  `integrations/ada-voice/README.md` § Drop 17 — cp module, merge
  manifest, append guide, cp scenario, apply count_cap patch, then
  `render-tool-profiles.py` + lane env key.
- First real-key `kind=interactive` / `kind=static`+route call is the
  live smoke; OSM path is keyless and unit-covered.
