# Timer consumer-canary on idc03 failing (OPS-1149)

## What was wrong

`consumer-canary.service` on idc03 failed `result=exit-code` on the 05:21,
11:21 and 13:02 +07 runs — **by design**: `scripts/audit/consumer-canary.py`
exits 1 whenever it finds live retired-hostname refs, and timer-sentinel
surfaces that as a timer-alert card. The journal showed the same two stale
refs every run:

1. `mn01` — `~/.config/caddy/Caddyfile.mn01` `handle /apps/board*` reverse-proxied
   to `https://tony-dell.taila0626a.ts.net:443` (board static upstream; the
   retired edge — documented as such in ssot.routes.yml's topology comment).
2. `ada-ha` — the `chaba-admin` lovelace dashboard had a node-red iframe at
   `https://tony-dell.taila0626a.ts.net/apps/node-red/?v=2`.

## What I changed (live surfaces)

- **mn01**: upstream repointed to `https://idc02.taila0626a.ts.net:443`
  (edited 13:18 +07). `caddy validate` clean; verified
  `http://127.0.0.1:8080/apps/board/index.html` → 200 through the chain.
- **ada-ha chaba-admin**: iframe rewritten to
  `https://idc02.taila0626a.ts.net/apps/node-red/?v=2` via
  `lovelace/config/save` over websocket on tony-omen (AGENTS.md rule —
  mutate live, then sync). node-red itself runs on tony-omen :1880; the
  idc02 web-origin (`~/web-srv/caddy/Caddyfile`,
  `/apps/node-red/* → 100.75.102.88:1880`) is the live edge. The public
  `tony-ha.surf-thailand.com` vhost has no node-red route (and is CF-Access
  gated), so the tailnet URL is the correct target for a dashboard iframe.

## Verified

- Manual rerun on idc03: `consumer-canary: CLEAN (9 greps + dashboards)`,
  exit 0, service `Finished` — journal 13:19 +07.
- Both previously-flagged surfaces confirmed clean at the consumer level
  (config text for mn01, ws-saved config for ada-ha).

## Repo trail (committed on this dispatch branch)

- `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` —
  refreshed via `sync-ada-ha-chaba-admin.py`, now matches live.
- `docs/ssot/infrastructure/ssot.routes.yml` — topology comment updated to
  the idc02 upstream.
- `docs/ssot/jobs/infrastructure/2026-11-08-consumer-canary-exit-code-two-stale-refs.yml` —
  incident record with per-fix detail and verify commands.

## Board

- `timer-alert-idc03-consumer-canary` → **done** (closed via /action do=close
  after a RESOLVED comment).
- `consumer-canary-standing-retired-hostnam-6aa4a2` — commented that both
  standing findings cleared.
- Filed follow-up `apps-yml-host-url-still-tony-dell-x42` (**OPS-1195**):
  `stacks/web/public/apps/apps.yml` still carries 42 `host_url:
  tony-dell.taila0626a.ts.net` entries rendered as absolute links by the
  /apps/ index — links work today (dell edge still answers) but are
  retired-host refs on a surface the canary does not grep. Card sequences
  migrate-entries-first, then add apps.yml to the canary GREPS set.

## Note

One 13:02 run also logged `board-api comment failed: timed out` — transient;
prior and subsequent posts succeeded. No action taken.

## How to verify

```
ssh idc03 'systemctl --user start consumer-canary.service'  # exit 0, "CLEAN"
ssh mn01 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/apps/board/index.html'  # 200
# ada-ha -> chaba-admin -> node-red panel loads from idc02.taila0626a.ts.net
```
