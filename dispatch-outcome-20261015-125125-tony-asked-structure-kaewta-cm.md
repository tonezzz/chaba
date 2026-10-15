# Dispatch outcome — ada-kk-cms-traffic (2026-10-15 12:51, runner idc03)

## Task

Structure Kaewta's CMS for traffic-cam awareness with truthful answers:
(1) zone-group filter on cam-wall-cms.py so only zones.yml `group:public`
zones emit pages; (2) timer run with COLLECTION=ada-cms-pages-kk writing
camwall-traffic + cam-traffic-* dossiers; (3) she reads via cms_read and
states freshness. vms-noble-* (group:private) excluded by design — Tony
answered "public-only" on 2026-10-12.

## Finding: already built and live — this run was verification

Both 2026-10-14 dispatches (222305 build+merge, 224058 timer arming)
completed the card. This session re-verified every deliverable end-to-end
against live state; nothing needed building.

## Verified (all live, this session)

- **Filter:** `CAMWALL_ZONE_GROUPS=public` + `COLLECTION` env knobs in
  `scripts/cam-wall/cam-wall-cms.py`; per-lane pub-hash/notify state;
  `zone:`-source boundary keeps the kk lane from touching private docs.
  `python3 -m unittest tests.camwall.test_cam_wall_cms` → 4/4 pass
  (KkLaneTest covers the privacy boundary).
- **Timer:** `cam-wall-cms-kk.timer` armed on tony-dell (`*:7/15`,
  Persistent). Journal for last 2h shows clean ticks at :22/:37/:52 —
  `zone group filter ['public'] -> ['burapha','chonburi','dohweb','rama9',
  'traffic'] · collection ada-cms-pages-kk` → `walls: 5 pages + 21 cams +
  index ok`, ~1s per run.
- **Dossiers:** MDDB `ada-cms-pages-kk` holds 5 camwall-* walls + 45 cam-*
  dossiers (en+th = 100 keys). `camwall-traffic` meta:
  `zone_group: public`, `zone_tab: Traffic`, `fresh_for: 1h`,
  `updated: 2026-10-15T05:52:01Z` (matches the 12:52 +07 tick — fresh).
  Zero private-zone keys (no noble-*, no tony-house) in the collection.
- **Her read path:** `ada-kk.service` active on idc03:8007; lane SSOT
  `cms_collection: ada-cms-pages-kk` + `cms_catalog_prime: true`;
  `cms_read` in persons.kk.tools. Pages carry `fresh_for`/`updated` meta
  so she can state freshness truthfully.

## Card state

Posted verification comment; card already in `review` on the live board
(moved there by the 10-14 finish; worktree snapshot was stale backlog).

## Result

All three deliverables live and verified: public-only filter publishing
to ada-cms-pages-kk every 15min from tony-dell, dossiers fresh and honest
about live/down/stale, Kaewta's lane configured to read them. Remaining
step is human: ask Kaewta a traffic question (e.g. Rama 9 / Burapha) and
confirm she cites camwall-*/cam-* pages with freshness.

## How to verify

- `ssh tony-dell 'systemctl --user list-timers cam-wall-cms-kk.timer'`
- `journalctl --user -u cam-wall-cms-kk.service` — the
  `zone group filter ['public'] -> [...]` line each tick.
- MDDB `POST /v1/get {collection: ada-cms-pages-kk, key: camwall-traffic}`
  — active, fresh `updated`, `fresh_for: 1h`.
- Ask Kaewta about Bangkok traffic — expect camwall-* citations +
  freshness statement.

## Caveats

- Pages refresh on 15min ticks; between ticks they can honestly flag
  stale past `fresh_for: 1h`.
- Noble estate stays excluded — needs an explicit policy exception via
  card request if ever wanted.
- Cam roster follows live registry manifests; count drifts run to run
  (21 cams published on the last tick).
