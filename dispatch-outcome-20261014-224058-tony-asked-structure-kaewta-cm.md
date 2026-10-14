# Dispatch outcome — ada-kk-cms-traffic (2026-10-14 22:40, runner tony-omen)

## Task

Structure Kaewta's CMS for traffic-cam awareness: (1) zone-group filter
on cam-wall-cms.py so only zones.yml `group:public` zones emit pages;
(2) timer run with COLLECTION=ada-cms-pages-kk writing camwall-traffic +
cam-traffic-* dossiers; (3) she reads via cms_read and states freshness.
vms-noble-* (group:private) excluded by design — Tony answered
"public-only" on 2026-10-12.

## Findings on entry

Dispatch 20261014-222305 (same card, ~20min earlier) had already
implemented and merged everything: `COLLECTION` + `CAMWALL_ZONE_GROUPS`
env knobs in `scripts/cam-wall/cam-wall-cms.py`, per-lane pub-hash/notify
state, `systemd/cam-wall-cms-kk.{service,timer}`, KkLaneTest coverage,
docs + job trail (`docs/ssot/jobs/ada/2026-10-14-kk-cms-traffic-feed.yml`),
plus a real first publish into ada-cms-pages-kk. Only remaining step was
arming the timer on tony-dell, which the served checkout couldn't do
until the merge landed.

## What this session did

- Verified merged code in worktree; `python3 -m unittest
  tests.camwall.test_cam_wall_cms` → 4/4 pass (KkLaneTest covers the
  privacy boundary: private-zone docs untouched).
- Verified live collection before touching anything: `camwall-traffic`
  active, `zone_group: public`, `zone_tab: Traffic`, `fresh_for: 1h`.
- Confirmed tony-dell's served checkout already had the merged code and
  the kk timer was NOT installed — then installed and armed it:
  `cp systemd/cam-wall-cms-kk.{service,timer} ~/.config/systemd/user/`,
  `daemon-reload`, `enable --now cam-wall-cms-kk.timer`
  (next tick :7/15 — 22:52 first scheduled run).
- Ran `systemctl --user start cam-wall-cms-kk.service` on tony-dell to
  verify ExecStart end-to-end. Journal: `zone group filter ['public'] ->
  ['burapha','chonburi','dohweb','rama9','traffic'] · collection
  ada-cms-pages-kk` → `walls: 5 pages + 21 cams + index ok · superseded
  24 archived 0`, clean finish.
- Post-run collection check: 5 camwall-* walls + 42 cam-* docs (21 cams ×
  en+th) active; `camwall-traffic` now `updated: 2026-10-14T15:42Z`.
  Kaewta's pre-existing media-*/inbox docs untouched. The 24 superseded
  pages are this generator's own lifecycle pass (cams that left the live
  manifests since the first publish — roster fluctuates) — intended
  supersede-by-construction, not data loss.
- Posted completion comment to the card.

## Result

Card deliverables all live: filter merged, timer armed and ticking on
tony-dell every 15min, dossiers in ada-cms-pages-kk are fresh and honest
(zone_group=public, fresh_for=1h, real live/down/stale states). Kaewta's
cms_read collection is ada-cms-pages-kk, so she can answer traffic
questions and state freshness from the page meta.

## How to verify

- `ssh tony-dell 'systemctl --user list-timers cam-wall-cms-kk.timer'`
- `journalctl --user -u cam-wall-cms-kk.service` on tony-dell — look for
  the `zone group filter ['public'] -> [...]` line each tick.
- MDDB `POST /v1/get {collection: ada-cms-pages-kk, key: camwall-traffic}`
  — active, fresh `updated`, `fresh_for: 1h`.
- Ask Kaewta about Bangkok/Rama 9 traffic — she should cite
  camwall-*/cam-* pages with freshness.

## Caveats

- Pages refresh every 15min from tony-dell ticks; between ticks they can
  honestly flag stale if manifests age past `fresh_for: 1h`.
- Noble estate coverage stays excluded — needs explicit policy exception
  via card request if ever wanted.
- Cam count per run follows the live registry manifests (21 cams this
  run); roster churn is normal and supersede-by-construction keeps the
  corpus honest.
