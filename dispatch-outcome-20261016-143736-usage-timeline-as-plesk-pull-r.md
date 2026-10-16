# Dispatch outcome — wp-usage-pull-render-plesk-worker (attempt 3)

Card: `wp-usage-pull-render-plesk-worker` (OPS-0661) — usage timeline as
Plesk pull-render worker.

## Prior failure addressed

Attempt 2 (idc03, 2026-10-15 15:47) executed the deploy successfully but
its repo-side changes were **lost**: the session checkpoint commit
(`ea43e8e9`) could not push (`https://github.com` has no auth on idc03),
the worktree was GC'd, and master's `ssot.jobs.yml` ended up with **no
`usage-feed-push` registration** — the live timer on idc03 had no manifest
entry, so the next `render-jobs --install` would have silently removed it.
This run re-landed the lost repo state, verified everything live, and
recorded the deploy quirks attempt 2 found.

## Verified live state (this run)

- **idc03 exporter**: `usage-feed-push.timer` armed, every 15m; last run
  14:30 SUCCESS — `15 usage rows, 100 spend rows -> pushed -> idc02`.
- **idc02 edge**: `/feeds/usage.json` bearer gate LIVE on apex
  `https://surf-thailand.com/feeds/usage.json` — verified `403` anon,
  `200` + valid `chaba-usage/v1` body with token (read from the idc02
  Caddyfile, never printed). `monitor.*` is CF Access-gated (302 on every
  path) — apex was the right call.
- **idc02 wp-watch.py**: heartbeat-usage-pull freshness check confirmed
  applied (USAGE_STALE_MIN=90 + seen-marker; `.bak-usagepull-20261015155605`).
  Host-local script, not repo-tracked — recorded in the runbook.
- **Plesk side**: still pending — `GET /wp/v2/ops-event?slug=heartbeat-usage-pull`
  returns `[]` on both public and h3 origin. Tony's three panel steps
  remain (open request `plesk-side-is-the-only-step-left-h3-pane-a9d972`):
  plugin zip v0.5.0 upload, wp-config constants, Plesk Scheduled Task
  (WP-Cron hourly fallback self-arms).

## Changes in this worktree

- `docs/ssot/infrastructure/ssot.jobs.yml` — re-added `usage-feed-push`
  job (idc03, systemd, every 15m) matching the **live rendered unit
  byte-for-byte** (verified via `render-jobs.py --host idc03` → diff
  against `~/.config/systemd/user/usage-feed-push.{service,timer}`).
- `systemd/generated/idc03/usage-feed-push.{service,timer}` — rendered
  artifacts of the above.
- `docs/ssot/infrastructure/ssot.routes.yml` — usage-feed `public_host`
  corrected `monitor.surf-thailand.com` → `surf-thailand.com`, note records
  the CF Access finding + live verification.
- `docs/ssot/apps/ssot.wp-boards.yml` — watchdog block updated:
  feed+edge+watch live, worker pending, actual hostname recorded.
- `docs/ssot/jobs/infrastructure/2026-10-15-usage-pull-render-plesk.yml` —
  status → `deployed-pending-plesk-panel` + `deployed_state` block with
  the verified facts and quirks (caddy restart-not-reload, `/data,Z`
  fossil dir inside the container, lost job registration).

## Result

Infrastructure half of the design is live and now correctly reflected in
SSOT — feed pushes every 15m, edge gate verified, independent freshness
watch armed. Remaining work is Tony's one-time h3 Plesk panel setup
(~5 min, spelled out in the open board request and the runbook); once the
plugin runs, `heartbeat-usage-pull` appears and wp-watch starts gating it.

## Verify

    curl -o /dev/null -w '%{http_code}' https://surf-thailand.com/feeds/usage.json   # 403
    ssh idc03 'systemctl --user status usage-feed-push.service -n 3'                 # SUCCESS
    ssh idc02 'ls -la ~/.config/containers/caddy/data/www/feeds/'                    # fresh file
    # after Tony's Plesk steps:
    curl -s "https://boards.h3.gizmo-thailand.com/wp/index.php?rest_route=/wp/v2/ops-event&slug=heartbeat-usage-pull"

Note: `chaba-board-api.service` was down on tony-dell this session (user
systemd manager stuck in `starting`); a `--no-block` start job was queued.
Card comms could not be posted — this doc is the trail.

## lessons:
- Dispatches on hosts without GitHub auth (idc03) lose all repo edits on
  worktree GC — verify job/timer registrations exist in origin/master, not
  just on the host, before ending the session.
- `monitor.surf-thailand.com` rides Cloudflare Access — 302s every path;
  machine-pull feeds must use apex `surf-thailand.com` or another
  grey-cloud name on the idc02 edge.
- caddy-edge Caddyfile edits need `restart`, not `reload` — the bind
  mount pins the file to a stale inode.
- The caddy-edge container contains literal `/data,Z` and `/config,Z`
  dirs (a `-v :Z` flag typo'd `,Z` at some point) — config written against
  them still works, confusing but harmless.
- wp-watch.py on idc02 is host-local (`~/.local/bin/`), not repo-tracked —
  SSOT prose is the only record of changes to it.
