# Dispatch outcome — kk-places-tool (DECISION 2026-11-26 Tony: split)

**Registered tool: `kk_places`** (ada-voice drop 23, staged in chaba only —
no host touched, no runner-agent.py scp, per the split decision).

## What changed

Chaba-repo half of card `kk-places-tool` (OPS-0506): a Google Places (New)
lookup tool for the kk member lane, following the established tools.d drop
contract (place_report / map_embed / trip_calendar).

New files:
- `integrations/ada-voice/backend/tools.d/kk_places.py` — the tool.
  `POST /v1/places:searchText` for `query=` (optional `lat`/`lon` ~2 km
  bias, `limit` 1–10 default 3, `lang`) or `GET /v1/places/{place_id}`
  for dossier re-verify. Key: `ADA_PLACES_API_KEY` else
  `GOOGLE_MAPS_API_KEY`; keyless → `ok:false needs_key` + maps search URL.
  Best match upserts the `place-<slug>` dossier via
  `runner.cms_publish_page` (domain `places`, `fresh_for` 7d, private
  default; `public='yes'` gated on `confirmed='yes'`; publish failure
  never fails the lookup; empty result writes no page).
- `integrations/ada-voice/backend/tools.d/manifest.kk_places.yml` —
  manifest fragment (policy read, secondary_allowed, timeout 60s).
- `integrations/ada-voice/backend/tool_guide.kk_places.yml` — guide entry.
- `integrations/ada-voice/tests/scenarios-live/kk_places.yaml` — smoke
  scenario (tool-lint requires one per new tool).
- `integrations/ada-voice/docs/ssot/ssot.tool-surface.kk-places.patch` —
  count_cap 113→114 ratchet (deployer bumps by one if the base moved).
- `tests/ada/test_kk_places_drop.py` — 19 no-network adapter tests.
- `docs/ssot/jobs/ada/2026-11-26-kk-places-tool.yml` — job trail.

Edited:
- `docs/ssot/apps/ssot.apps.ada-persons.yml` — `kk_places` in
  `persons.kk.tools.include` + `kk-cms-only` + `kk-parity` bench
  profiles (parity test requires the exact mirror).
- `docs/ssot/infrastructure/ssot.tools.yml` — `places.lookup` registry row.
- `integrations/ada-voice/README.md` — Drop 23 section (files, install,
  contract, env).
- `docs/kb/lane-place-reports.md` — references now name `kk_places`.

## Result / verification

- `tests/ada/test_kk_places_drop.py`: **19/19 pass** (uv venv — mn01 has
  no system pytest; `uv run --with pytest --with pyyaml --with httpx`).
- `tests/ada` suite: **465 passed**, 4 failed — all four are pre-existing
  patch-gate tests (`cast_loop_breaker`, `correction_command`,
  `persona_photo_store`, `write_fidelity_drop`) whose OLD staged patches
  diverged against the sibling `~/CascadeProjects/ada-voice` checkout
  (post-merge drift); unrelated to this change — none read the new files.
- Bench-profile parity assertions replicated in plain python: PASS.
- YAML syntax + SSOT validation via pre-commit hook: PASS.
- Commits on `dispatch/20261126-222251-decision-2026-11-26-tony-split`:
  `0b565e4112` (the drop) + `d50fbd96b1` (hook assessment refresh).
  Not pushed — merge-sweep owns that.
- tool-lint itself lives in ada-voice (`scripts/tool-lint.py`) and runs at
  deploy; the staged surface mirrors drops 17/19/22 which passed it.

## Not done (explicitly out of scope per the split)

- No `scp`/deploy of runner-agent.py or any host. The ada-voice landing
  (cp tool + merge manifest/guide + scenario + count_cap patch +
  tool-lint + deploy-ada.sh + lane restart) and the env key check
  (`ADA_PLACES_API_KEY` or `GOOGLE_MAPS_API_KEY` with Places API enabled
  in the lane backend env) are Tony/host gates — see the job trail's
  `follow_ups` and README Drop 23 install steps.

## How to verify

```
uv run --with pytest --with pyyaml --with httpx \
  python -m pytest tests/ada/test_kk_places_drop.py -x -q   # 19 passed
```

lessons:
- mn01 has no pytest/httpx — `uv run --with pytest --with pyyaml --with
  httpx --with requests --with pillow --with websockets` runs the ada
  drop suites fine; tests/ada needs all six deps for full coverage.
- tests/ada patch-gate suites (cast_loop, correction_command,
  persona_photo_store, write_fidelity) fail on mn01 because they diff
  OLD staged patches against the drifted sibling ada-voice checkout —
  pre-existing environmental failures, not regressions.
- Recent drops (19 host_status, 22 asset_save) staged NO count_cap
  patch — the 113 base in ssot.tool-surface.kk-places.patch assumes
  map_embed's bump is still the latest; deployer bumps by one if moved.
- ssot.dev-system.assessment.yml is refreshed by the pre-commit hook on
  every commit and is perpetually dirty afterward — expected, the
  checkpoint sweeps it.
- tools.d modules that call runner.cms_publish_page are the kk lane's
  only CMS write path (cms_publish_page decl is profile-excluded) —
  kk_places writes the place dossier the same way place_report does.
