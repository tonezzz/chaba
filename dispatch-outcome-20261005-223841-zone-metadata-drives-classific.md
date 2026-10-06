# camwall-zone-metadata — zones.yml SSOT

## What changed

Zone→tab mapping and camera membership moved out of three hardcoded
locations into a single SSOT, `scripts/cam-wall/zones.yml`, consumed via
a new shared loader `scripts/cam-wall/zone_meta.py`.

- **`scripts/cam-wall/zones.yml`** — per-zone `group` (private|public),
  `site`, `area`/`info` (en+th), `interval`/`warm`, `cams`
  ([label, kind, key, *alts]) or `registry_group` (expanded from
  frigate/cameras.json). Top-level `tabs` maps group→display label
  (Security/Traffic/Unsorted), `devices` maps DVR→site/area (replaces
  DEV_AREA), `labels` carries the slug→display overrides.
- **`cam-wall-pull.py`** — ZONES/LABELS/TRAFFIC_ZONE_MAP deleted; roster
  built from zones.yml (`load_zones` + `load_registry_zones`). Each
  `manifest-<zone>.json` now carries `group`/`site`/`tab`. New
  `write_zones_index()` writes `data/zones.json`
  ({tabs, zones:{zone:{group,site,tab,cams}}}) — one HTTP-readable file
  for the CMS sidebar. Zones with no cams are skipped loudly; a zone
  absent from zones.yml can never silently pull.
- **`cam-wall-cms.py`** — ZONE_INFO/ZONE_INFO_TH/AREA/AREA_TH/DEV_AREA
  deleted; areas/info via `zone_meta.classify`, cam classification via
  `cam_classify` (DVR device wins over listing zone). `mddb_add` stamps
  meta `zone_tab`/`zone_group`/`zone_site` (multi-zone pages tag the
  sorted set they span) and folds classification into the dedup hash so a
  zones.yml edit republishes affected pages.
- **`docs/ssot/apps/ssot.apps.camwall.yml`** — implementation map updated.
- **`docs/ssot/jobs/infrastructure/2026-10-05-camwall-zone-metadata.yml`**
  — job trail incl. the ada-pi follow-up contract.

## Semantics

`group` (private|public) is the privacy semantic; `tab` is the display
label keyed by group unless a zone pins `tab:`. A zone absent from
zones.yml classifies as `unsorted` — a visible bucket on the sidebar,
never the old silent Security guess.

## Verified

- `py_compile` clean; zones.yml parses (8 zones, 2 devices, 3 tabs).
- ZONES built from yaml is equivalent to the old dict — including
  registry-expanded traffic/burapha/chonburi (11 cams each).
- **Card's verify test**: a cam named `q7x-random-cam` (no prefix) inside
  vms-noble-club classifies → tab `Security`, group `private`,
  site `noble-club` — classification comes from zone metadata, not the
  camera name. Unknown zone `mystery-wall` → `Unsorted`.
- `zones.json` written correctly over a fake DATA dir; manifests render
  with correct bilingual titles; `zone_*` meta lands in mddb_add payloads;
  roster-audit's importlib path to `ZONES`/`slug` still works.

## Not done here (follow-up, other repo)

The third consumer — `pwa/cms/index.html` — lives in the **ada-pi** repo
(served by ada-pi-pwa on idc01:8001), outside this worktree. Its
SEC/TRAF_ZONES + slug-prefix/title-regex guessing should be replaced with
a fetch of `/apps/camwall/data/zones.json` (or the `zone_tab`/
`zone_group` page meta) — contract documented in the job yml.

## How to verify in production

1. After the puller next runs: `curl -s https://tony-dell.taila0626a.ts.net/apps/camwall/data/zones.json`
   — expect `tabs` + per-zone group/site/tab + cam membership; a retired
   zone dir shows `tab: "Unsorted"`.
2. `jq .group,.site,.tab data/<zone>/manifest-<zone>.json`.
3. After cam-wall-cms next runs: `ada-cms-pages` docs carry
   `meta.zone_tab/zone_group/zone_site`; page republish happens once
   (classification folded into dedup hash).
