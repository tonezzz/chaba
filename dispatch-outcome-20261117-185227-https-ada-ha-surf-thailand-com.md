# dispatch-outcome — chaba-nest hosts view: replace tony-ha iframe

Card: `chaba-nest-hosts-view-replace-tony-ha-if-053226` · runner: tony-omen · 2026-11-17

## Result

Chose **option (a)** — fully native views. The card's blocker ("entities live
on tony-ha") was dissolved: `telemetry-ha-push.py` on tony-omen already mirrors
MDDB `device-telemetry/<dev>/latest` into HA REST sensors, so a second
env-only instance now mirrors the identical entity ids into ada-ha :8125.

## What changed

**Infra (live on tony-omen)**
- New job `telemetry-ha-push-ada` in `docs/ssot/infrastructure/ssot.jobs.yml`:
  same script as `telemetry-ha-push`, `HA_URL=http://127.0.0.1:8125`,
  `HA_TOKEN_FILE=%h/.config/secrets/ada-ha-token.env` (pre-existing ada-ha
  LLAT, verified `POST /api/states`). Rendered + installed via
  `render-jobs.py --install`; timer enabled, fires `*:0/5` — first manual run
  pushed all 8 hosts fresh=on; ada-ha went from 32 → 200 states.

**Dashboard (live on ada-ha)**
- `ssot.chaba-nest-dashboard.yml` extra_views: `/hosts` and `/services` are now
  native masonry views via a compact `template: host_fleet|service_fleet`
  marker; `chaba-nest-build.py` expands them into the same markdown fleet
  table + per-host entities cards as tony-ha's chaba-admin (dropped
  `custom:layout-card`, `switch.mac_plug` — neither exists on ada-ha;
  `card_mod` kept). All 53 service-view + all hosts-view entity refs verified
  present on ada-ha.
- `/or-panel` iframe repointed `tony-ha.surf-thailand.com` →
  `idc02.taila0626a.ts.net` (Access-free tailnet origin) and `aspect_ratio`
  dropped per the documented panel-iframe rule (bare iframe fills the panel).
- Pushed via `chaba-nest-build.py --apply` — 13 views saved.

## Verification

- Live `lovelace/config chaba-nest` over ws: **0 `tony-ha.surf-thailand.com`
  refs**, hosts=masonry×9, services=masonry×8, or-panel=panel+bare-iframe→idc02;
  `aspect_ratio` count 0. Generator output verified identical to live.
- `https://ada-ha.surf-thailand.com/chaba-nest/hosts` → 200.
- `systemctl --user list-timers telemetry-ha-push-ada.timer` → enabled, ran
  on schedule (19:05), next 19:10.
- iPhone-Safari done-criteria: single sidebar (native cards, no iframed HA
  page), no CF Access iframe anywhere, masonry collapses to one column.

## Trail

- Job doc: `docs/ssot/jobs/home-assistant/2026-11-17-chaba-nest-hosts-native.yml`
- Commit: `cbad05009b` on `dispatch/20261117-185227-https-ada-ha-surf-thailand-com`

## Residual / notes

- `sensor.dispatch_probe` left `unavailable` on ada-ha (one-shot token probe;
  not in the entity registry, clears on restart).
- Topic views still iframe the CMS viewer on `idc03.taila0626a.ts.net` —
  tailnet-only, no CF Access, already single-sidebar; unchanged by design.
- If `TELEMETRY_DEVICES` grows upstream, mirror it in this job's env too.
