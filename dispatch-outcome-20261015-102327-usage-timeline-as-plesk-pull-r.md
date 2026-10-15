# Dispatch outcome — usage timeline as Plesk pull-render worker

Card: `wp-usage-pull-render-plesk-worker` (OPS-0661) · 2026-10-15

## What changed

Design implemented end-to-end in the worktree; nothing deployed (deploy
needs Tony's Plesk/edge access — raised as a board request with defaults).

- `scripts/litellm/usage-feed.py` (new) — idc03 exporter. Aggregates
  `~/CascadeProjects/ada-voice/data/usage.jsonl` + `LiteLLM_SpendLogs`
  (podman psql primary, admin-API fallback — same pattern as
  `daily-ledger.py`) into a `chaba-usage/v1` JSON of flat day×lane rows —
  aggregates only, no raw session data, safe to cross the public edge.
  `--push` scp's to `idc02:.config/containers/caddy/data/www/feeds/
  usage.json` via `.tmp`+`mv` (fleet ssh mesh supplies idc03→idc02).
  Smoke-tested locally against a synthetic usage.jsonl.
- `integrations/wp-boards/chaba-boards.php` — 0.4.2 → 0.5.0. New
  `chaba_usage_pull_run()` + `chaba_usage_render()`: fetches the feed
  (`CHABA_USAGE_FEED_URL`/`CHABA_USAGE_FEED_TOKEN` wp-config constants,
  bearer auth), buckets it into one rolling private `report` post
  (slug `usage-ledger`, meta report_type/period/source_key), and bumps
  ops-event `heartbeat-usage-pull` every run including failures.
  Hourly WP-Cron fallback armed on init.
- `integrations/wp-boards/usage-pull-cron.php` (new) — Plesk Scheduled
  Task entry point: walks up from the plugin dir to `wp-load.php`
  (works under the /wp subdir install), loads WP, runs the worker,
  echoes one line into the task log. CLI-only.
- `docs/ssot/infrastructure/ssot.routes.yml` — registered route
  `usage-feed`: static `/feeds/usage.json` on `vps-public` edge,
  `public_host: monitor.surf-thailand.com`, `auth: bearer-token`.
- `docs/ssot/infrastructure/ssot.jobs.yml` — job `usage-feed-push`
  (idc03, every 15m); activates on next `render-jobs.py --host idc03
  --install`.
- `docs/ssot/apps/ssot.wp-boards.yml` — v0.5.0 note, `usage_pull`
  writer entry, watchdog freshness line (wp-watch adds
  `heartbeat-usage-pull` to its list).
- `docs/ssot/jobs/infrastructure/2026-10-15-usage-pull-render-plesk.yml`
  (new) — full design/runbook: topology, feed schema, idc02 Caddyfile
  bearer-gate snippet, ordered deploy steps, open decisions, caveats,
  verification commands.
- Drive-by fix: `docs/ssot/jobs/kanban/2026-10-15-board2-living-board.yml`
  had a YAML syntax error (`— #ticker` mid-scalar truncated by `#`);
  entries converted to `>-` folded scalars. `ssot-validate-all.mjs` now
  reports 0 errors (2411 files).

## Not done / gated on Tony

- Deploy: redeploy chaba-boards zip v0.5.0 in wp-admin; add the two
  wp-config constants; create the Plesk Scheduled Task (every 15m →
  `wp-content/plugins/chaba-boards/usage-pull-cron.php` or
  `wp eval 'chaba_usage_pull_run();'`); add the bearer-gated `/feeds/`
  handle to idc02's `~/.config/caddy/Caddyfile`; extend wp-watch's
  freshness list with `heartbeat-usage-pull`.
- Board request `usage-pull-worker-code-landed-deploy-nee-549e41`
  carries the 3 defaults to confirm: rolling report post ★ /
  scp-push transport ★ / monitor.surf-thailand.com hostname ★.
- Caveat: PHP not installed on the dispatch host — the worker is
  reviewed but not `php -l` linted; first Plesk run is the syntax
  check, and a fatal still surfaces via a stale heartbeat.

## Verify

- `python3 scripts/litellm/usage-feed.py --dry-run` on idc03 prints a
  valid feed (usage + spend rows).
- Post-deploy: `curl -H "Authorization: Bearer $TOK"
  https://monitor.surf-thailand.com/feeds/usage.json`; private report
  `usage-ledger` in wp-admin; anonymous REST read of
  `ops-event?slug=heartbeat-usage-pull` shows `modified` bumping.
- Board: comm + request posted on the card.
