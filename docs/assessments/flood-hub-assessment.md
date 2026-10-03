# Google Flood Hub — Assessment & Integration Report

Status: **living document** — updated in place as we learn more, before making any contact. Git history is the version trail; freeze a dated snapshot only when we send something external.
Created: 2026-09-30 · Last updated: 2026-09-30

## TL;DR

The shared link is Flood Hub centered on **Ongkharak district, Nakhon Nayok** (14.0893°N, 101.0840°E) — one of the three districts currently being hit by runoff released from Khun Dan Prakan Chon Dam (active crisis since ~Sep 27; 300+ people in shelters, Ban Na / Pak Phli / Ongkharak downstream watch).

Flood Hub itself is **worth integrating**: free, CC BY 4.0, daily-updated 7-day riverine forecasts with a proper REST API (`floodforecasting.googleapis.com/v1`). The catch: API access is **waitlist-gated** (reported wait: months). Natural fit with our stack — and we already have the delivery machinery: the `flood-report` CMS pages auto-regenerate from news feeds via `flood-news-update.py`, so Flood Hub gauge data can slot in as a second managed block once we have a key.

## What the link points at

- Center: 14.0893°N, 101.0840°E, zoom ~7.8 → Bang Sombun area, **Ongkharak district, Nakhon Nayok province** (TH-26), on the Nakhon Nayok River basin.
- Shared via Facebook (`fbclid`), almost certainly because of the **current flood event**: Khun Dan Prakan Chon Dam discharge + runoff from Namtok Nang Rong / Khlong Maduea. As of Sep 29 the situation was still critical downstream. The site is JS-rendered so gauge IDs at that exact point can't be resolved without the API (see below).

## Current state in our stack (checked 2026-09-30)

Flood coverage already exists in **ada-cms**, but it's *news digests*, not Flood Hub data:

- **`flood-report`** (CMS rollup, "สถานการณ์น้ำท่วมล่าสุด") — auto-regenerated hourly by `flood-news-update.py`; feeds: `bangphli`, `samutprakan`, `bangkok-th`, `bangkok-en` (Google News RSS). Has `children: [flood-report-nongdon]`.
- **`flood-report-nongdon`** — leaf page covering Saraburi/Lopburi/Chao Phraya dam feeds. **Collapsed 2026-09-30**: was a single-child rollup of `flood-report-nongdon-saraburi` (identical feeds) — redundant layer removed; now `flood-report` → `flood-report-nongdon` (leaf) directly.
- Generator: `scripts/ada/flood-news-update.py` + `scripts/ada/flood-news-feeds.json` (chaba repo). Pages use `<!-- flood-news:auto -->` managed blocks — a clean insertion point for a second managed section with gauge data.
- Registry: `ada-cms-automation` MDDB collection — each generated page has a config doc (`run_now` flag → worker regenerates; `POST /api/cms/pages/{slug}/regenerate` triggers it). **Gotcha**: the registry doc caches its own effective config and *wins over* feeds.json — collapsing/splitting a page requires updating BOTH feeds.json and the registry doc, plus the page doc's meta (generator merges stale keys; `parent`/`children` now have removal paths in `publish()`).
- Nothing in ada-cms currently uses Flood Hub / gauge data — the Flood Hub assessment lives only in this repo doc.

## Document management — the "two versions" question

We don't need two versions of *this* report. Proposed structure, consistent with existing conventions (SSOT → render, mutate-live → sync-back):

| Layer | Location | Role | Edit rule |
|---|---|---|---|
| Canonical | `docs/assessments/flood-hub-assessment.md` (this file, repo) | Working assessment — detailed, accumulating | Edit directly; git history = versions |
| Presentation | ada-cms `flood-report*` pages | Household-facing situation digest | **Never hand-edit the auto block** — content flows one-way via `flood-news-update.py` |
| Optional mirror | `flood-hub-assessment` CMS page (en+th, `parent: flood-report`) — **exists since 2026-10-03** | Rendered copy of this doc | Republish on demand (MDDB `add` / `cms_publish_page`) when this doc changes materially; body stamps canonical source + rendered date |
| Snapshot | `flood-hub-assessment-YYYY-MM-DD.md` | Frozen copy for external contact/submission | Created only when we actually send something |

Rule of thumb: **one canonical location per document; anything elsewhere is a generated, timestamped copy.** The CMS flood pages aren't duplicates of this report — different audience (household vs. engineering), different content (news/gauges vs. service evaluation).

## Service assessment

### What it is

- Google Research product (`sites.research.google/floods`, aka g.co/floodhub). Two AI models: a **hydrologic LSTM** (Nearing et al., *Nature* 627, 2024 — the operational model) forecasting river discharge, and an **inundation model** estimating affected area + depth.
- Riverine flood forecasts **up to 7 days out**, refreshed **daily**, covering **150+ countries / ~2B people** per current marketing (Bellingcat's June-2025 snapshot said 80+ countries, 1,800+ high-confidence sites, 460M people — coverage expanded since).
- Map shows color-coded gauge pins (normal → warning → danger → extreme), per-gauge hydrograph vs. thresholds, inundation layers, inundation history, basin view. Alerts also surface in Google Search/Maps/Android notifications.
- Gauge types: **real gauges** (agency data, e.g. GRDC) and **virtual HYBAS gauges** (`hybas_<id>`, HydroBASINS river reaches — most of Thailand's coverage is likely these). Each has `qualityVerified` (model meets Google's eval bar) and `hasModel` flags; UI defaults to verified only, "expert mode" shows lower-confidence gauges.
- Fully free, data is **CC BY 4.0**, no account needed to view. Thai-language UI exists (cities.google/intl/th_ALL/flood-hub).

### Limitations (honest list)

- **Riverine only.** The Bang Phli / Thepharak Rd flooding our `flood-report` tracks is urban drainage/pluvial — Flood Hub gauges may show nothing there. (The API does expose `flashFloods:search` and `significantEvents:search`, which partially covers this — needs testing once we have a key.)
- Forecasts are **approximate** — the site itself says "for informational purposes only, check official sources" (= RID/thaiwater.net/DDPM for us). Cross-checking is mandatory for alerts we act on.
- Virtual gauges without `qualityVerified` can be materially wrong; treat as advisory.
- Daily cadence — not a real-time sensor. Fine for 1–7-day outlook, useless for minute-level dam-discharge events.
- API is waitlist-gated. Flood Hub's own UI key is embedded client-side (the TAK-NZ ETL project documents that the UI calls the same public `floodforecasting.googleapis.com` endpoints), but the sanctioned path is the waitlist — use that, not their key.

## Programmatic access

| Item | Detail |
|---|---|
| Endpoint | `https://floodforecasting.googleapis.com/v1` (REST, API-key auth, no OAuth) |
| Access | [Waitlist form](https://docs.google.com/forms/d/e/1FAIpQLSfcKhe3CHsncM-_NQ66zLheEfXKnNbDPBtuIT7BSYCqYkmOaA/viewform) → approval email → reply with Google Cloud Project ID → enable `floodforecasting.googleapis.com` |
| Cost/license | Free, CC BY 4.0 |
| Key methods | `gauges:searchGaugesByArea` (region code `TH` or polygon loop), `floodStatus:queryLatestFloodStatusByGaugeIds`, `floodStatus:searchLatestFloodStatusByArea`, `gauges:queryGaugeForecasts` (8-day daily values), `gaugeModels:batchGet` (warning/danger/extreme thresholds), `flashFloods:search`, `significantEvents:search`, `serializedPolygons/{id}` (KML inundation polygons) |
| Historical | **Inundation History** 1999–2020 (`gs://flood-forecasting/inundation_history`), **GRRR** runoff reanalysis/reforecast 1980–2023 (Colab-linked dataset) |
| Verify | Google publishes a [Colab notebook](https://colab.research.google.com/drive/1et0vjN9coLck11YhORyprgtOvCuaErVd?usp=sharing) to test a key |
| Caveat | HydroBASINS catchment polygons are NOT in the API (TAK-NZ confirmed); `serializedPolygons` only covers flood/inundation areas |

Existing consumers worth copying: **TAK-NZ/etl-floodhub** (poll → CoT map points, poll cadence ~120s), **Deltares DELFT-FEWS** `GoogleFloodHubV1GaugeForecast` import (request pattern: `queryGaugeForecasts?gaugeIds=...&issueTimeStart=T0-25h`, batch ≤500 gauges), **floodops** (Python connector mirroring Google's colab).

## Integration plan

Ranked by effort/benefit. All assume waitlist approval except #1.

1. **Sign up for the waitlist now** (zero code). We already have GCP projects (gev-gemini/Gemini API) — pick one, submit the form with a "home automation + local alerting" use case. Approval reportedly takes months; queue it.
2. **HA REST sensors on michael-dev** (once keyed): `gauges:searchGaugesByArea` once to enumerate Thai gauges near us (Chao Phraya basin for Bang Phli-side relevance + Nakhon Nayok basin for the current event + Saraburi/Lopburi for the nongdon pages), then poll `floodStatus:queryLatestFloodStatusByGaugeIds` every ~6–12h. Store gauge IDs + thresholds in SSOT. Follow the `mha_mirror_*`/package pattern, not ad-hoc YAML.
3. **Extend `flood-news-update.py`** — instead of a new job, add a `<!-- flood-hub:auto -->` managed block to `flood-report` + nongdon pages: today's gauge severities + 7-day trend per watched basin, next to the news digest. The regeneration plumbing (automation registry, `run_now`, worker) is already built.
4. **Ada alert path**: `flood_status` tool in ada-pi reading HA entities or hitting the API from idc01; severity ≥ WARNING → LINE push via Yomi + spoken note. Scenario test under `tests/scenarios-live/` (fits the existing `deep_dive_flood_report`/`flood_situation` family).
5. **GEV overlay**: `serializedPolygons/{id}` returns KML inundation areas — Cesium in gods-eye-view can drape these. Medium effort; only worthwhile while there's an active event or as an optional layer.
6. **Display/vcast banner**: watched gauge ≥ WARNING → banner on vcast displays / CCTV wall. Cheap once #2 exists.
7. **Cross-source sanity**: pair Flood Hub with thaiwater.net (HII) / RID so Ada can say "Google says X, RID gauge says Y" — matches the verify-before-alarming duty.

## Ways to contribute

- **Feedback/bugs**: in-site "Send feedback", plus dedicated [bug form](https://docs.google.com/forms/d/e/1FAIpQLSekz7lXXGh5AS2lpGK-jdI3w0CdlXCzjbZlOmM3esCP1qtUSQ/viewform) and [feedback form](https://docs.google.com/forms/d/e/1FAIpQLSdUcndasiipwf-Bb_Evv2flbnwWl4AgtgcHbiPJBTRYKupOWQ/viewform). Pilot participants can request a meeting with the team — a genuine channel; they explicitly invite it.
- **Data**: Google's stated bottleneck is public discharge records. Channels: `floodforecasting@google.com` (help publishing data) and the **Caravan** open streamflow dataset (how hydromet agencies contribute; WMO/GRDC feed 25 countries through it). **Thailand is not currently a Caravan contributor** — if Tony has contacts at RID/HII, advocating Thai gauge data into Caravan is the highest-impact contribution available; it would directly improve Flood Hub accuracy for the rivers flooding right now.
- **Open-source**: no Home Assistant Flood Hub integration exists (only TAK/DELFT-FEWS/floodops). Publishing our REST-sensor config or a small HACS component would be a real contribution — CC BY 4.0 permits it.
- **Ground truth**: XMEye CCTV wall (noble-club / noble-a DVRs) + observations already compiled could validate predictions-vs-reality locally; anomalies are exactly what the bug form / pilot meetings want.

## Next actions

1. ~~Submit the waitlist form~~ — **done 2026-09-30**. Now: watch Tony's Gmail for the approval email (reportedly months). Focus item parked: `docs/ssot/focus-inbox/2026-09-30-193000-flood-hub-api-waitlist.yml`.
2. On approval email: reply with Google Cloud Project ID **`flood-watch-510211`** (created 2026-09-30) → enable `floodforecasting.googleapis.com` → create key restricted to the API + idc01 IP (`157.85.110.99`) → store `FLOODS_API_KEY` in `~/.config/secrets/flood-forecasting.env`.
3. Verify with `scripts/ada/flood-hub-check.py` (ready): `gauges --region TH` lists gauges, `status <id>...` shows severity/trend, `forecast <id>...` dumps the 8-day series.
4. Meanwhile `flood-report` keeps working off news data — no blocker.
5. ~~Housekeeping~~ — **done**: `flood-report-nongdon-saraburi` collapsed into `flood-report-nongdon` (leaf); orphaned CMS page + automation docs deleted.
6. When the key lands: #2 sensors → #3 managed block → #4 Ada alert. GEV overlay only if a map view is actually wanted.

## Update log

- **2026-10-03** — published CMS mirror: `flood-hub-assessment` (en+th) under `parent: flood-report`, `attribute=assessment`, hand-maintained (no `generated_by`). Only `parent` is set on the child — `children` on `flood-report` is owned by the generator and would be re-stamped on the next run.
- **2026-09-30** — initial assessment; link geocoded to Ongkharak, Nakhon Nayok (active dam-discharge flood); confirmed flood-report CMS pages exist and auto-regenerate (`flood-news-update.py`, last run 17:16); no Flood Hub data in ada-cms yet; found duplicate nongdon slugs.
- **2026-09-30 (later)** — waitlist form submitted by Tony. Added `scripts/ada/flood-hub-check.py` (verify/enumerate tool, stdlib-only) + focus-inbox item to track the pending approval.
- **2026-09-30 (evening)** — GCP project created: `flood-watch-510211` (ready to reply to approval email). Collapsed `flood-report-nongdon-saraburi` → `flood-report-nongdon` (leaf); learned the ada-cms-automation registry caches effective config and overrides feeds.json — collapses must clear both + page meta; patched `publish()` to drop stale parent/children keys.
- **2026-09-30 (night)** — **GEV flood layer prototyped** on branch `flood-history-layer` (tony-dell `~/gods-eye-view`, worktree `~/gev-wt-flood`): pulled 4 Inundation History cells (public `gs://flood-forecasting/inundation_history`, CC-BY-4.0) covering lat 10.3–16.4 / lon 97.8–103.5 → merged to 3 per-risk `.geojsonl` layers (high/med/low wet-frequency, ~3.2 MB) in `src/data/local_data/flood_inundation/`; registered in `localLayers.js`, `layerState.js` URL tokens (h/j/n), `set_layer_visibility` enums + name mapping, voice aliases. Tests pass on tony-dell (layerState 50, localGeojson 22, gevActions 74); `npm run build` green, assets bundle correctly.
- **2026-09-30 (late night)** — **Deployed**: branch merged to GEV main @ `f7dd661` on tony-dell; dist patched (api/models prefixes + iPad msaaSamples) and staged into the live Caddy bind `~/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/gev/`; verified 200 on `/apps/gev/` + all 3 flood assets. `tools.json` (gev-gemini bridge) regenerated with the 3 new layer ids; bridge restarted. Scenario `flood_situation` ran 2× on idc01 — PASS (exit 0), live `cms_publish_page` writes confirmed (`flood-coordinates-rayong`). Second NongDon regression found + fixed: the live `ada-flood-news` worker runs the **deployed copy** on tony-dell `~/CascadeProjects/chaba` (not this repo) — it re-stamped `children` at 21:47/22:02; synced the fixed script+feeds there, healed registry+page meta, `cms-audit` R3 clean now. Learned: config changes to live workers must deploy to `~/CascadeProjects/chaba` on tony-dell, not just commit here.

## Sources

- developers.google.com/flood-forecasting (+ /rest reference) — API surface, waitlist, licensing, datasets, forms
- support.google.com/flood-hub (answers 15636593, 15638004, 16364206, 16364306, 16364606, 16508958) — product facts, Caravan/`floodforecasting@google.com` contribution path, waitlist reality (months)
- github.com/TAK-NZ/etl-floodhub — endpoint usage patterns, UI-key observation, polygon caveat
- publicwiki.deltares.nl (DELFT-FEWS) — `queryGaugeForecasts` request shape, 25h `issueTimeStart` trick, ≤500-gauge batches
- github.com/bellingcat/toolkit — coverage snapshot (June 2025), verified-vs-low-confidence toggle
- dailynews.co.th / thaipbs.or.th — current Nakhon Nayok event context (Sep 28–29)
- OSM Nominatim — link location geocode (Ongkharak, Nakhon Nayok, TH-26)
- Local: `scripts/ada/flood-news-update.py` + `flood-news-feeds.json`; MDDB `ada-cms-pages` / `ada-cms-automation` collections; `docs/ssot/focus-inbox/processed/handoff-devin-handoff-latest-flood-situation-report-for-bang.yml`
