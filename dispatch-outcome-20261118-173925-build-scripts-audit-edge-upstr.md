# dispatch-outcome: edge-upstream-dead-port-audit

**Result: done.** `scripts/audit-edge-upstreams.py` built, unit-tested,
run live against the fleet, and wired into the audit cadence — committed
as `f63904c6fb` on `dispatch/20261118-173925-build-scripts-audit-edge-upstr`
(not pushed; no deploys per card rules).

## What changed

- **`scripts/audit-edge-upstreams.py`** (new) — fleet edge-upstream audit.
  Per host: parses `tailscale serve status --json` (background Web/TCP +
  Foreground sessions) and verifies every proxy/TCPForward target against
  the host's `ss` listener table (loopback targets) or an HTTP probe
  (remote targets, expect non-5xx); parses each host's Caddyfiles
  (`~/.config/caddy` host-net edges, `~/web-srv/caddy` + `camwall-edge`
  slirp containers) and probes every `reverse_proxy` upstream per vhost.
  Rows `{host, surface, mount, upstream, status, evidence}`; statuses
  ok/dead/degraded/skipped; **exit 1 on dead|degraded** — timer-ready.
  `--write` emits `reports/edge-upstreams/` artifacts + `edge-upstreams/
  <host>` metas (lib.report); `--ship` rsyncs metas to the served
  checkout (remote pushback); `--alert` files deduped board-api `/inbox`
  entries (24h per surface).
- **`tests/test_audit_edge_upstreams.py`** — 8 tests, incl. the incident
  fixture (serve :8125 → dead :8125 flags dead; repoint → :8123 passes),
  Foreground/TCPForward parsing, tailnet-IP-only bind case, Caddyfile
  vhost/matcher/multi-upstream parsing, URL-error classification.
- **`ssot.jobs.yml`** — job `audit-edge-upstreams` on con01, hourly
  `*:41`, `--all --write --ship --alert`; rendered
  `systemd/generated/con01/audit-edge-upstreams.{service,timer}` and
  regenerated `docs/ssot/generated/jobs.*.yml` (regen also swept in
  previously un-rendered jobs: ada-retention-*, chaba-pytest-suite).
- **`ssot.reports.yml`** — nodes `edge-upstreams/{tony-omen,tony-dell,
  idc02,idc03,mn01}`, observe:remote, cadence 1h.
- **`ssot.health.home.tailscale.yml`** — new `ada-ha-edge-8125` http check
  (end-to-end probe of the exact surface that died; mcp-health surface).
- **`docs/kb/edge-upstream-audit.md`** — runbook; **`docs/ssot/jobs/
  infrastructure/2026-11-18-edge-upstream-audit.yml`** — lifecycle trail.

## Verified

- 8/8 unit tests pass. Live `--all` from idc02: **118 ok / 2 degraded /
  3 dead / 1 skipped, exit 1** — the script would have caught today's
  incident at both layers (serve mount dead AND caddy upstream 502).

## Real findings flagged (NOT fixed — owner call; will alert via the job)

1. `tony-omen serve :8444 -> 127.0.0.1:9005` dead (ha-live inactive) —
   also dead via `100.75.102.88:9005` in web-srv and 502 through the
   idc02 `http://:8444` shadow edge.
2. `michael-dev.surf-thailand.com -> https://idc02.taila0626a.ts.net:8124`
   TLS mismatch — the serve `:8124` mount routes.yml expects is missing;
   backend is plain HTTP on the tailnet IP. Fix: `tailscale serve --bg
   --https=8124 http://127.0.0.1:8124` on idc02, or repoint upstream to
   `http://`.
3. `web-srv -> frigate:5000` — no frigate container on idc02 (the
   /frigate/* route 502s since the web origin migration).

## How to verify

- `python3 scripts/audit-edge-upstreams.py --all` — table + exit code.
- `python3 -m pytest tests/test_audit_edge_upstreams.py` — 8 pass.
- After merge + `render-jobs.py --host con01 --install` (deploy step, not
  done here): `systemctl --user list-timers audit-edge-upstreams.timer`
  on con01; nodes `edge-upstreams/<host>` on the fleet report.
