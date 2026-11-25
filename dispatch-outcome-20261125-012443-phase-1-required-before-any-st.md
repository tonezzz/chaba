# dispatch outcome — camwall-retire-to-wiki (attempt 2)

## What happened

Attempt 1 (tony-omen) completed Phase 1 — consumer map + runbook — but the
session died before Phase 2 and its branch was never merged. This run
fetched that branch (`dispatch/20261124-223438-...` @ 383838c4b6) from
tony-omen's repo over ssh and cherry-picked the two doc commits, then
executed Phase 2 after Tony's `ada-snapshot-only` answer.

## Phase 2 executed (live, verified)

**Stopped/disabled:**
- idc03: `cam-wall-cms-vps.timer`+`.service`
- idc02: `camwall-render-check.timer`+`.service`
- tony-omen: `cam-wall-cms.timer`, `cam-wall-cms-kk.timer`,
  `cam-wall-roster-audit.timer` (+services) — all three were LIVE there
- tony-dell: already parked/disabled (cms/cms-kk/roster `.parked`, pull
  disabled) — verified only

**Kept (the ada-snapshot-only plane):**
- `cam-wall-pull-vps.timer` on idc02+idc03 (30s, OWN/PUSH lane split)
- `camwall-edge.service` on idc02+idc03 (:8380)
- input-bridge `/camwall` GET+POST (pull gating + ada zone list)
- zones.yml, all data dirs, `~/.config/camwall.env`, `camwall-push` keys

**Deviation (flagged on card):** the approved option said stop
edge+route, but ada-voice `stale_snapshot()`/`_camwall_fallback()` fetch
thumbs via `ADA_CAMWALL_BASE` → `/apps/camwall/data/*` → edge :8380 —
stopping them would kill the fallback being kept. Narrowed the route to
`/apps/camwall/data/*` instead; wall UI/vcast/CMS surface retired.

**Repo changes (commit 007f6ee0cd on dispatch branch):**
- `ssot.routes.yml` camwall path → `/apps/camwall/data/*` + retirement note
- `stacks/web/Caddyfile` narrowed block; `routes.json` re-rendered
- `public/apps/camwall/{index.html,tour-th001.html}` deleted
- `ssot.apps.camwall.yml` PARTIALLY RETIRED banner
- `ssot.audit.hosts.yml` expected units pruned (edge+pull-vps kept)
- `ssot.quality.yml` ci.camwall-smoke removed; workflow deleted
- `chaba-audit.py` probe → `/apps/camwall/data/zones.json`
- `docs/kb/retired-apps/camwall.md` — Phase-1 map recovered + executed
  checklist, live-apply notes, restore steps
- `docs/ssot/jobs/infrastructure/2026-11-2{4,5}-camwall-*.yml` job trail

**Live apply:** tony-dell `web` container restarted with narrowed
Caddyfile (mirror file restored after — in-memory config is narrowed;
restart once more after next served-mirror sync). idc02 `web-srv`
Caddyfile patched + caddy reload; static wall files moved to
`~/web-srv/public/apps/camwall-retired-bak/` (web-srv-sync has no
--delete).

## Verify

- `curl https://tony-dell.taila0626a.ts.net/apps/camwall/data/zones.json` → 200
- `/apps/camwall/yolov8n.onnx` (non-data) → 404
- idc02/idc03: `systemctl --user list-timers` shows only
  `cam-wall-pull-vps.timer`; `podman ps` shows `camwall-edge` up
- data freshness: `~/.local/share/camwall/data/zones.json` updating
  every cycle on both VPS hosts

## Follow-ups (documented in camwall.md)

- After next tony-dell served-mirror sync: `systemctl --user restart
  web.service` once so on-disk/in-memory Caddyfile agree.
- Existing MDDB `camwall-*`/`cam-*`/`cctv-walls`/`dvr-wall` pages are stale
  snapshots — left in place by design.
- Full-stop remains possible later via the runbook's restore/stop steps.

lessons:
- Single-file bind-mounted Caddyfiles: `caddy reload` can log "config is
  unchanged" on a stale inode after git checkout replaced the file —
  restart the unit instead (same lesson as the 2026-11-25 mn-ha-dev move).
- web-srv-sync rsyncs `public/` WITHOUT `--delete` — repo file deletions
  never propagate to idc02 web-srv; delete live copies by hand.
- Dispatch worktree branches on other hosts are fetchable via
  `git fetch ssh://<host>/home/tony/CascadeProjects/chaba <branch>` —
  salvages unmerged prior-attempt work.
- tony-dell has TWO web surfaces: `web.service` container (host-net :80,
  chaba-tony-dell mirror checkout) is the live one for
  tony-dell.taila0626a.ts.net; idc02 `web-srv` :8099 is a second origin.
- camwall option-(b) catch: "keep Ada snapshot fallback" requires the
  whole pull-vps→edge→/data/* HTTP path — verify consumer fetch paths
  before stopping "edge+route" literally.
