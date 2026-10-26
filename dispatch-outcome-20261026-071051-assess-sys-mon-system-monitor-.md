# dispatch-outcome — sys-mon → chaba-admin/monitor (card sys-mon-system-monitor-de88ff)

## Assessment

"sys-mon" already existed as a pipeline, not an app: `scripts/host-loads.py`
(5-min SSH sampler → `reports/host-loads/host-loads.yml` + L1 meta node) feeding
the "Host loads" section of `SYSTEM-REPORT.md`, which the existing
chaba-admin `monitor` tab already iframes (`/apps/system-report/`). Two gaps:

1. **Dead producer** — the sampler was piggybacked on `tony-dell-monitor.service`;
   when dell was drained the sampler went dark (last sample 2026-10-23, node stale).
2. **No live view** — host loads only appeared inside the daily-regenerated report.

## What changed (branch `dispatch/20261026-071051-...`, commit b4f739e6)

- `stacks/web/public/apps/system-report/{index.html,app.js}` — new live "Host
  loads" table at the top of the page: fetches `data/host-loads.yml` every 60 s
  (load 1/5/15 bar, mem used/total, disk %, sample age, unreachable pill);
  falls back to the `host_loads` block embedded in `system-report.yml`.
- `ssot.jobs.yml` — new job `chaba-host-loads` (idc02, `every: 5min`, systemd):
  runs the sampler from the exec checkout, then installs the yml into both the
  exec-checkout app data dir and `~/web-srv/public/apps/system-report/data/`.
- `systemd/generated/idc02/chaba-host-loads.{service,timer}` — rendered.
- `ssot.reports.yml` — host-loads generator now `chaba-host-loads.timer`.
- `ssot.home-assistant.dashboards.yml` — monitor-tab note documents the live table.
- `docs/home-assistant/dashboards/chaba-admin-current.json` — re-synced from live.
- `docs/ssot/jobs/infrastructure/2026-10-26-sys-mon-monitor-page.yml` — trail.

## Live changes (no push needed)

- `~/.config/systemd/user/chaba-host-loads.{service,timer}` installed +
  `enable --now` on idc02 — fired at 07:18 and 07:23 (5-min cadence confirmed).
- App files copied to `~/web-srv/public/apps/system-report/` (idc02 edge, live
  instantly) and to idc03's served checkout
  `~/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/system-report/` so
  the hourly `web-srv-sync` doesn't revert them (kanban-commit will sweep the
  identical content into master — clean convergence with this branch).
- chaba-admin `monitor` view iframe URL bumped `?v=6` → `?v=7` via
  `push-dashboard.py` on tony-omen (websocket save — verified in live config).

## Verified

- `curl https://idc02.taila0626a.ts.net/apps/system-report/data/host-loads.yml`
  → fresh `generated_at` (07:23, second tick).
- Edge serves new `index.html` (hosts table) + `app.js?v=9` (loadHosts).
- Live dashboard config (fetched over ws) has monitor → `.../system-report/?v=7`.
- Sampler output identical coverage to pre-drain: 6/9 hosts; unreachable
  {kk-mac, macbook, michael-ha} — unchanged baseline, not a regression.

## Follow-ups noted in the trail doc

- kk-mac/macbook/michael-ha SSH reachability (same three dark under dell).
- con01's daily report keeps the audit fallback for its Host loads section
  (reports/ is gitignored; the live table supersedes it).
- `tony-dell-monitor.sh` still calls host-loads.py on dell — dead path, left
  for the dell teardown card.
