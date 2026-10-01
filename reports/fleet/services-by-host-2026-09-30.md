# Running services by host — 2026-09-30 (~06:30 +07)

Live inventory (`podman ps` + `systemctl --user list-units --running`),
desktop noise filtered out. Complements the daily `audit-hosts` YAML
dumps (which record deltas vs SSOT, not a readable list).

## tony-dell (workstation, 15 GiB, HDD)

**Containers (24 up):** bserver, chaba-postgres-16, gemini-ollama-proxy,
gev-gemini, google-home-mcp, gpu-queue, gpu-queue-processor, mddb
(**follower**), michael-dev, node-red, notebooklm-mcp, notebooklm-rest,
raceman-php, raceman-web, redis, rview-api, rview-live, status-data-api,
tony-ha, trade-api, trade-automation, weaviate, web (Caddy), yomi-api

**User services (~60):** ha-live, michael-dev, secrets-console,
dnsmasq-postgre, chaba-tunnel, barrier-client, playlived,
playlive-omen-cdp-tunnel, mcp-rview(+oauth-proxy), mcp-debug-sse,
mcp-link-monitor, mha-state-push, websockify-macbook, camera-monitor,
camera-panel, cast-browser-proxy, chrome-cdp-headless, clip… (+desktop)

**Failed:** ada-flood-news, ddesktop@autostart, audit-cast,
focus-dispatcher-overnight, overnight-assessment, xiaomi-token-refresh
(+ cosmetic portal units)

## tony-omen (desktop/GPU, 30 GiB)

**Containers:** netdata, ollama, sensor-reader (+1)

**User services:** open-jev (:8777 tailnet, capped 250%), weaviate-
embed-proxy, weaviate-search, cast-browser, cast-shots-http,
cookie-bridge, chaba-watch, ghostroute-watcher, mddb-tunnel,
openclaw-gateway, rika-watchdog, tailscale-connections, playlived,
rclone-gdrive, barriers, clip-sync-dell, michael-dev, filter-chain

**Failed:** arp-inventory-scan, chaba-audit-watchdog, chaba-report-feed,
focus-dispatcher(-overnight), michael-dev-parity; cast-desktop@0 stopped
on purpose (unconsumed stream)

## idc01 (public VPS, mddb leader)

**Containers:** mddb (**leader**), mddb-panel, caddy-edge,
gemini-ollama-proxy, input-bridge, ollama, open-notebook,
open-notebook-surreal, ada-scenario-smoke, vcast-headless-2/4

**User services:** ada-ha-tony, ada-ha-michael, ada-pi-pwa, ada-dev,
ada-line-relay, ada-tg-relay, jev-student, doc-archive, obsidian-vault

**Failed:** ada-bench-casting, ada-scenario-reports, mddb-backup(!),
mddb-memory-standard — the backup/monitor units warrant a look

## idc02 (new offload VPS)

**User services:** open-jev (:8777 tailnet, healthy)
**vcast-real@6/7** (headless Chromium) were active earlier — not in the
latest list; may have been stopped by the provisioning session.

## mn01 (home-lab node)

**Containers:** xmeye-vms-vnc, google-home-mcp, icloud-mcp,
notebooklm-mcp

**User services:** yolo-xiaomi (+yolo-ipad-1/2 bound tailnet :8780),
weaviate-embedding (:5000), xmeye-vms, playwright-server

**Failed:** mn01-canary (pre-existing)

## kk-macbook — offline (16d, expected)

## Notes

- mddb follower is planned to move dell → idc02 (see
  `mddb-follower-migration-plan` report; benchmark: cold-open 5–16 s on
  idc02 vs ~3.5 h on dell HDD).
- idc01's failed `mddb-backup.service` is worth checking — nightly
  backup may have stopped firing.
