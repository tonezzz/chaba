# Dispatch outcome — ada-kk-cms-traffic (2026-10-14 22:23)

## Task

Structure Kaewta's CMS for traffic-cam awareness with truthful answers:
(1) zone-group filter on cam-wall-cms.py so only zones.yml `group:public`
zones emit pages; (2) timer run with COLLECTION=ada-cms-pages-kk writing
camwall-traffic + cam-traffic-* dossiers; (3) she reads via cms_read and
states freshness. vms-noble-* (group:private) excluded by design — Tony
answered the card request "public-only" on 2026-10-12.

## What changed (worktree, merge pending)

- `scripts/cam-wall/cam-wall-cms.py` — new lane env knobs:
  `COLLECTION` (default ada-cms-pages) picks the MDDB collection;
  `CAMWALL_ZONE_GROUPS` (comma/space allowlist of zones.yml `group:`
  values, empty = all) filters the publish set right after manifest
  load. Dedup/notify state files are now per-lane
  (`_cms-pub-hash-kk.json`, `_cms-notify-state-kk.json`) so lanes can
  share CAMWALL_DATA without suppressing each other's writes.
  `regen_reports_index` now passes `collection=COLLECTION`. The existing
  `zone:`-source boundary in `_successor_for` already keeps a
  public-only lane from superseding private-zone docs — verified in the
  new test.
- `systemd/cam-wall-cms-kk.service` + `cam-wall-cms-kk.timer` — new
  units for tony-dell: `COLLECTION=ada-cms-pages-kk`,
  `CAMWALL_ZONE_GROUPS=public`, `*:7/15:00` (offsets dell :0/15 and VPS
  :2/15 ticks). No ADA_NOTIFY_* — her lane does not ping Tony's Ada.
- `tests/camwall/test_cam_wall_cms.py` — new `KkLaneTest`: public-only
  publish set, all writes to ada-cms-pages-kk, no dvr-wall, private-zone
  doc untouched. All 4 tests pass (`python3 -m unittest`).
- Docs: `zones.yml` header (filter consumer + unsorted exclusion),
  `ssot.apps.camwall.yml` CMS entry, `ssot.cms.yml` producers list.
  SSOT validation clean (2354 files, 0 errors).
- Job trail: `docs/ssot/jobs/ada/2026-10-14-kk-cms-traffic-feed.yml`.

## Live result (already in production)

A real first publish ran from this worktree on idc02 — manifests for the
five public zones fetched over the tailnet
(`/apps/camwall/data/<zone>/manifest-<zone>.json`), then a real
generator run with the kk env. `ada-cms-pages-kk` now holds
**5 camwall-* walls + 43 cam-* dossiers + cctv-walls + regenerated
reports-index** (en+th). Verified via MDDB get/search: `zone_group:
public`, `zone_tab: Traffic`, `fresh_for: 1h`, honest live/down/stale
states (e.g. traffic 6/11 cams live — real answers, not hopeful ones).
Zero private-zone pages; her pre-existing docs untouched.

## Remaining (needs the merge + one command on tony-dell)

The timer can't be armed from the worktree — its ExecStart points at the
served `chaba-tony-dell` checkout which lacks the new code until merge.

    cp systemd/cam-wall-cms-kk.{service,timer} ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now cam-wall-cms-kk.timer

Until it runs, her pages are a one-shot snapshot and will honestly flag
⚠STALE past fresh_for=1h.

## How to verify

- `python3 -m unittest tests.camwall.test_cam_wall_cms` (worktree) —
  KkLaneTest covers the privacy boundary.
- `POST /v1/get {collection: ada-cms-pages-kk, key: camwall-traffic}`
  on MDDB — live page, zone_group=public, fresh_for=1h.
- Ask Kaewta "is there traffic on Rama 9?" — she reads camwall-rama9 /
  cctv-walls via cms_read (her cms_collection = ada-cms-pages-kk;
  catalog prime already lists the new keys).
- After timer install: `systemctl --user list-timers cam-wall-cms-kk`
  on tony-dell; journal shows `zone group filter ['public'] -> [...]`.

## Caveats

- Image/montage URLs in the pages are tailnet (tony-dell.ts.net);
  pages carry no meta.public so they stay tailnet-only by default.
- Noble estate coverage stays excluded — needs an explicit policy
  exception via card request if ever wanted.
