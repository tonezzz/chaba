# Running services by host — 2026-10-01 (~08:30 +07)

**Status: all 5 reachable hosts up; no critical service outages.
idc01 disk at 96% — needs cleanup soon. omen vacuumed (~9 GB freed).**

## Latest

- **2026-10-01** — idc01 `mddb-backup` fixed (`podman cp` + port-mapped
  verify + 20-min rescan window); first **verified** clean-DB backup
  `mddb-filecopy-mddb-20261001-0649.db`.
- **2026-10-01** — tony-omen vacuum: podman images 8.2→2.5 GB,
  chrome caches cleared, journals vacuumed. `uv` cache (22 GB) locked
  by a live process — deferred.
- **2026-09-30** — mddb follower (dell) finished its ~3.5 h rescan at
  19:26, healthy/read-only, replaying reindex backlog.

Sections: [tony-dell](#tony-dell-workstation-15-gib-hdd) ·
[tony-omen](#tony-omen-desktopgpu-30-gib) · [idc01](#idc01-public-vps-mddb-leader) ·
[idc02](#idc02-new-offload-vps) · [mn01](#mn01-home-lab-node) ·
[Watch list](#watch-list)

## tony-dell (workstation, 15 GiB, HDD) — load ~8, disk 84%

**Containers (25):** bserver, chaba-postgres-16, gemini-ollama-proxy,
gev-gemini, google-home-mcp, gpu-queue(+processor), inspiring_darwin,
mddb (**follower**), michael-dev, node-red, notebooklm-mcp/-rest,
raceman-php/-web, redis, rview-api/-live, status-data-api, tony-ha,
trade-api, trade-automation, weaviate, web (Caddy), yomi-api

**User services (~60):** ha-live, secrets-console, dnsmasq-postgre,
chaba-tunnel, barrier-client, playlived, playlive-omen-cdp-tunnel,
mcp-rview(+oauth-proxy), mcp-debug-sse, mcp-link-monitor,
mha-state-push, websockify-macbook, camera-monitor/-panel,
cast-browser-proxy, chrome-cdp-headless, filter-chain, gpu-queue…

**Failed:** ddesktop@autostart, audit-cast, focus-dispatcher-overnight,
overnight-assessment, xiaomi-token-refresh (+cosmetic portal units —
pre-existing noise)

## tony-omen (desktop/GPU, 30 GiB) — load ~3, swap 28/71 GiB used

**Docker:** netdata, ollama, sensor-reader, funny_swanson
**Podman:** michael-dev
**User services (48):** open-jev (:8777 tailnet, 250% cap),
weaviate-embed-proxy/-search, cast-browser, cast-shots-http,
cookie-bridge, chaba-watch, ghostroute-watcher, mddb-tunnel,
openclaw-gateway, rika-watchdog, tailscale-connections, playlived,
rclone-gdrive, barriers, clip-sync-dell, michael-dev, filter-chain…
Devin Desktop up (19 procs; renderer crash at 21:11 Sep-30 recovered —
main process 19h+ uptime).

**Failed:** arp-inventory-scan, chaba-audit-watchdog,
chaba-report-feed(now removed?), focus-dispatcher(-overnight),
michael-dev-parity; cast-desktop@0 intentionally stopped.

## idc01 (public VPS, mddb leader) — load ~0.9, **disk 96% ⚠**

**Containers:** mddb (**leader**), mddb-panel, caddy-edge,
gemini-ollama-proxy, input-bridge, ollama, open-notebook(+surreal),
ada-scenario-smoke, vcast-headless-2/4

**User services:** ada-ha-tony/-michael, ada-pi-pwa, ada-dev,
ada-line-relay, ada-tg-relay, jev-student, doc-archive, obsidian-vault

**Failed:** ada-bench-casting, ada-scenario-reports,
mddb-memory-standard — and mddb-backup was failing until today's fix.

## idc02 (offload VPS, 15 GiB) — idle, disk 6%

**Containers:** vcast-real-6, vcast-real-7 (headless Chromium)
**User services:** open-jev (:8777 tailnet, healthy)
No failed units. Planned: mddb follower (migration plan published).

## mn01 (home lab, 7 GiB) — load ~1.2, disk 20%

**Containers:** xmeye-vms-vnc, google-home-mcp, icloud-mcp,
notebooklm-mcp
**User services:** yolo-xiaomi (+ipad-1/2, :8780 tailnet),
weaviate-embedding (:5000), xmeye-vms, playwright-server, filter-chain

**Failed:** mn01-canary, notifyd (pre-existing)

## kk-macbook — offline (expected, travel)

## Watch list

- **idc01 disk 96%** (92/96 GB): backups 33 GB (needs retention trim),
  containers 13 GB, CascadeProjects 14 GB, stray `mddb-seed3/4.db`
  ~3.8 GB in ~ — prune next pass.
- **omen dangling docker volumes** (~2.2 GB): `mddb-data` holds a
  Sep-23 `mddb.db` (pre-rebuild), `postgres_data` 77 MB,
  `weaviate_data` 22 MB — keep or delete after deciding whether the
  old DB copy has forensic value.
- **omen swap 28/71 GiB** — mostly in `/data/hibernate.swap`; Devin
  renderers hold most RAM. Drains slowly; reboot clears.
- **dell mddb follower** still replaying binlog backlog (leader reindex
  churn); converging on its own.
- **uv cache lock** — rerun `uv cache prune` on omen when idle.
