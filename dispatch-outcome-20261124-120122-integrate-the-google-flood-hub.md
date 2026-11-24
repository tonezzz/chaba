# Dispatch outcome — flood-hub-integration (attempt 2)

## Result: repo-side integration COMPLETE; live activation BLOCKED on two externals

The card is conditioned on "once waitlist approval lands". As of 2026-11-24:

1. **Waitlist approval has NOT landed** — card note still says BLOCKED,
   focus-inbox item still draft, no approval evidence in comms. Only Tony
   can confirm (check Gmail, reply with GCP project `flood-watch-510211`).
2. **idc01 is offline** — tailscale last-seen ~33 days (warm-DR node per
   card idc01-return-role). The spec's secret host + IP-restricted key
   (157.85.110.99) cannot be provisioned until it returns, OR the secret
   host moves to tony-dell (which runs the flood timers today) — a spec
   deviation needing Tony's call. Raised as a board request.

Attempt 1 left no artifacts (empty run log, clean worktree) — nothing to
fix; this run built the full key-ready surface.

## What changed (all in worktree, uncommitted→committed on dispatch branch)

| File | Change |
|---|---|
| `scripts/ada/flood-hub-lib.py` | NEW — shared stdlib Flood Hub client: `api_key()` (FLOODS_API_KEY/env file), `search_gauges`, `get_gauges` (batchGet names), `latest_statuses_by_gauge_ids`, `search_latest_statuses_by_area`, `statuses_for_config` (gauges-or-areas config resolver), `query_forecasts`, `get_serialized_polygon` (GEV KML), severity/trend rank + TH/EN labels |
| `scripts/ada/flood-news-update.py` | `<!-- flood-hub:auto -->` second managed block: `fetch_fhub_block`/`render_fhub_block`/`apply_fhub_block`; inserts right after the news block; per-block item-line dedup so unchanged data never churns revisions; **skips silently without FLOODS_API_KEY or on API error — news path cannot regress** |
| `scripts/ada/flood-news-feeds.json` | `flood_hub.areas` on `flood-report` (นครนายก-องครักษ์ + เจ้าพระยาตอนล่าง) and `flood-report-nongdon-saraburi` (สระบุรี-ลพบุรี + เขื่อนเจ้าพระยา) — coarse bounding loops pending gauge enumeration |
| `scripts/ada/flood-hub-alert.py` | NEW — severity watchdog: scans all pages' flood_hub configs, dedups by gaugeId (escalation-only re-alert), pushes via board_notify (default `ha,yomi` = HA iPhone + LINE when Yomi session valid), state file + `flood-hub-alert` registry doc for cms-auto-health, `--seed/--dry-run/--self-test` |
| `scripts/ada/flood-status.py` | NEW — JSON CLI backend for the Ada `flood_status` tool (`--page/--gauges/--region/--loop-*`, worst-first capped output with site/river enrichment); ada-pi wrapper still needed (separate repo) |
| `scripts/ada/flood-hub-check.py` | `area` command — `searchLatestFloodStatusByArea` worst-first summary for pre-enumeration verification |
| `docs/home-assistant/configuration/packages/flood_hub.yaml` | NEW — 4 watch areas × 4 REST sensors (severity, alert_count, worst_gauge, issued) = 16 sensors; POST searchLatestFloodStatusByArea, `x-goog-api-key: !secret flood_hub_api_key`, 6h scan; deploys to michael-dev on **idc02** via `deploy-config.sh --host dev` (needs `flood_hub_api_key` in `~/.config/michael-dev/secrets.yaml`) |
| `docs/ssot/jobs/infrastructure/2026-11-24-flood-hub-integration.yml` | NEW — activation runbook: blockers, severity mapping, 10-step checklist, verification |
| `docs/assessments/flood-hub-assessment.md` | update-log entry |

## Spec corrections found (worth noting)

- **"severity >= WARNING" doesn't exist in the API** — enum is
  `NO_FLOODING/UNKNOWN/ABOVE_NORMAL/SEVERE/EXTREME`; UI warning≈ABOVE_NORMAL.
  Implemented alert floor = `ABOVE_NORMAL` everywhere.
- **michael-dev moved** — tony-dell → idc03 → **idc02** (2026-10-26);
  `stacks/tony-dell|tony-omen/michael-dev/` are legacy. Canonical package
  home is `docs/home-assistant/configuration/packages/`.
- **IP restriction conflict** — key restricted to idc01 IP can't be used
  by HA sensors on idc02 or scripts on tony-dell; key needs all caller
  IPs or the pollers must live on idc01.
- `flood-news-update.py`/`flood-alert.py` already existed — "implement"
  in spec meant the flood-hub block/watchdog, which is what was built.

## Verification done

- `py_compile` all touched scripts; feeds.json + runbook YAML parse.
- `flood-news-update.py --page flood-report --dry-run` — live MDDB+RSS
  run, news block renders, fhub correctly skipped (no key).
- Mock-data tests: `render_fhub_block` Thai output + `apply_fhub_block`
  insertion/idempotency/dedup all pass; `flood-hub-alert` merge/dedup/
  escalation/render pass; Jinja templates render correctly under jinja2.
- No-key degrade: `flood-status.py` → JSON error exit 2;
  `flood-hub-alert.py` → exit 0 "nothing to poll"; `flood-hub-check.py
  area` → clear missing-key message.

## Not done (needs externals — see runbook checklist)

GCP enable + key creation, secret on idc01, live `flood-hub-check.py`
verification, live HA deploy + secrets.yaml entry, timer install for
flood-hub-alert.py, ada-pi `flood_status` tool registration, GEV KML
overlay (optional, lib helper ready).

lessons:
- board-api is NOT on localhost for dispatch hosts — use
  https://idc03.taila0626a.ts.net:10000 (tailnet serve injects the auth
  header; /comment + /request POSTs work from idc02).
- michael-dev HA runs on idc02 now, not tony-dell — check
  `systemctl --user cat michael-dev.service` before assuming stack dirs;
  canonical package source is docs/home-assistant/configuration/packages/.
- Flood Hub API severity enum has no WARNING — ABOVE_NORMAL is the real
  alert floor; card specs written from the UI colors will say WARNING.
- dispatch attempt 1 for this card produced zero artifacts (empty
  run.1.log) — "attempt 2" may just mean the runner died pre-start, not
  a code failure to fix.
