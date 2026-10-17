# tony-dell full-service migration runbook

Goal: empty tony-dell for multi-day hardware work (SSD + RAM) while the fleet keeps running — and leave behind a service-name layer so the next migration is a one-line proxy change, not a 152-file sed.

Context: 2026-10-16 collapse — 5400rpm HDD + 97% disk + unbounded podman health checks → load ~94, swap thrash, all TCP dead. Root-fixed (OPS-0718) but the hardware is the remaining liability.

## Current inventory (measured 2026-10-16)

77 user services + 41 system + 19 containers + 80 timers. No serial radios — everything is software-migratable. Only physically-pinned items:

- Ralink MT7601U USB WiFi adapter → `chaba-guest-lan` / `ha-guest-lan` / dnsmasq guest AP. Dies with the box unless the adapter moves to omen.
- Desktop session services (gvfs, pipewire, keyring, xfce-seat, evolution, barrier-client, at-spi, xdg-*) — die intentionally; they ARE the desktop.

## Target map

| Group | Target | Why |
|---|---|---|
| Canonical chaba checkout + board-api + kanban-commit + 80-timer fleet | **idc03** | backend-hub, 188G free, co-located with mddb. The single-writer pair MUST move together. |
| Status/report/monitoring APIs, secrets-console, GEV api, yt-live-api (+`~/.cache/yt-live-media`, `~/GoogleDrive/chaba-media-corpus/yt-live-media`), trade stack (trade-api, helm, bserver, gpu-queue), gemini-ollama-proxy, michael-ha-mcp-tunnel, notebooklm, websockify-* | **idc03** | Cloud-API workloads — VPS uptime/latency beats a home HDD box. |
| mddb-standby-pull + backup dirs, rclone-gdrive, dev-miniapp, logs/replicas | **idc02** | edge-primary, 220G free — cheap cold storage + offload legs. |
| **LAN-dependent**: tony-ha, ada-ha (`~/.config/home-assistant`, `~/.config/ada-ha` + the yt-live mounts above), go2rtc, camera-panel, plug-watch, cast-browser-proxy, nest-mgr, clip-sync-omen, gesture-relay, chrome-cdp-headless/xvfb-99, playlived | **tony-omen** | Must reach 192.168.2.x devices / LAN displays / the GPU. 22G RAM free. |
| Retire (don't migrate) | — | dev-miniapp-v0, mcp-debug-*, cam-frame-refresh (dead), stale tunnels, 5 unmerged dispatch worktrees. Multi-day window = free cruft purge. |

## THE FLEXIBILITY LAYER (do this FIRST — it halves every later step)

Problem: `tony-dell.taila0626a.ts.net` is hardcoded in **152 repo files** + live envs. Every future move repeats that cost.

Fix once: idc02 runs an edge reverse proxy (caddy or nginx) as the **stable service front door**:

```
board-api.surf-thailand.com        → backend board-api      (idc03)
status-api.surf-thailand.com       → backend status-data-api (idc03)
tony-ha.surf-thailand.com          → backend tony-ha         (omen)
edge.taila0626a.ts.net/apps/<svc>  → tailnet-only services   (idem)
```

- One caddy file = one upstream line per service. Migration = edit that line + reload.
- New service naming convention lands in SSOT (`ssot.system-map.yml` gets `front:` field); 152 refs get repointed ONCE, then never again.
- Auth note: board-api was ts.net-only — fronting it on public DNS needs the existing shared-secret header enforced at the edge before opening the name. If unsure, keep it tailnet-side under `edge.taila0626a.ts.net`.

## HA — honest assessment

Full HA (active-active, keepalived, pacemaker) = too complex/risky for this fleet, don't do it. Pragmatic tiering instead:

- **Tier 0 — board-api + canonical checkout**: active-passive. Primary idc03; standby on idc02 gets a git mirror every 5 min + a *stopped* board-api unit. Failover = flip edge upstream + `systemctl start` on standby. ~10 min MTTR, manual, cheap. (mddb-standby-pull already proves this pattern works — same shape.)
- **Tier 1 — tony-ha/ada-ha**: passive. HA's own backup lands on omen anyway after migration; restore-to-michael-dev is the documented warm path. Automations tolerate minutes of gap.
- **Tier 2 — everything else**: restart-on-boot, no replica. If it's down an hour, nobody drowns.
- Explicit no: VRRP/keepalived (L2-only, LAN-scoped), shared storage (single HDD box made this a non-question), k8s (4-core VPS fleet — the orchestrator would eat the capacity it saves).

## Phased cutover (each gate-verified before next)

0. ~~**Edge layer on idc02**~~ ✅ 2026-10-16 (`f95be36d0`) — `idc02.taila0626a.ts.net` serve→caddy:8088 passthrough + shadow ports 8123/24/25/8444/46/9230/3002. Caught: `http://127.0.0.1:N` is a host-matcher not a bind (use `bind`); serve certs need `tailscale cert` priming.
1. ~~**Kanban single-writer → idc03**~~ ✅ 2026-10-16 — writer family moved wholesale (14 svc/timer pairs incl. board-api, kanban-commit/dispatch/sync, sweeps, digests). Same path `%h/CascadeProjects/chaba-tony-dell` = units moved unchanged; `CHABA_SERVED_CHECKOUT` hook is path-based → self-identifies. board-api via `idc03.ts.net:10000` serve; `/apps/board-api` split to idc03 on both public edge + tailnet front; dell web keeps a compat shim (api stays OFF on dell — dual-writer is the forbidden state). `/apps/board` static still dell-served (mirror lag ≤15min). **Residuals:** ~~dell's `~/CascadeProjects/chaba-tony-dell` frozen stale dir~~ ✅ 2026-10-17 — `chaba-served-mirror-sync.timer` (hourly pull-only mirror via exec checkout's git-safe-pull; ~25 exec-only units keep fresh code, writers stay off). Stale pre-stop leftovers stashed (`frozen-writer-leftovers-2026-10-16`). idc03 needed `apt install nodejs` (pre-commit validator) + borrowed chaba deploy key via `gh-chaba` ssh alias — register a proper idc03 deploy key (OPS-0682 scope). GitHub push races: safe-pull handles.
2. ~~**Kanban single-writer → idc03**~~ ✅ done as phase 1 above — the 14-unit writer family moved wholesale rather than one unit at a time (single-writer meant the whole flock-writer set had to flip together).
3. **VPS APIs → idc02 (default) / idc03 (MDDB-or-board-local only)** — per service: rsync data dir + install unit + flip upstream. Gate: health endpoint per service. *Bias to idc02 since 2026-10-16: idc03 is near-saturated (load ~5 on 4 cores) after absorbing the writer family — see ssot.host-capacity.yml.*
   - ✅ 2026-10-17 batch 1: `chaba-monitoring-dashboard` (:3002 loopback+shadow, needed `MON_HOST` env — `server.listen(PORT)` was 0.0.0.0-public on VPS), `status-data-api` (podman :8000 loopback+shadow, edge `/api/*` upstream flipped), `chaba-report-api` (:8792 loopback+shadow, dell web upstream flipped — anon-write guard preserved), `secrets-console` (:8005 tailnet-IP bind — new URL `idc02.taila0626a.ts.net:8005`).
   - Reclassified LAN→omen: `yt-live-api` (casts to tony_tv_cast via localhost HA — NOT VPS-suitable). Deferred: GEV constellation (3 daemons + quadlet image + dead gev-cmd route), trade stack, yomi (MDDB-coupled → idc03-local).
   - ✅ 2026-10-17 batch 2: `websockify-macbook` (tailnet-IP bind :6080), `mcp-link-monitor` (chaba-repo python) → idc02; `overnight-assessment` job → idc03 (was failing nightly on frozen checkout). `ssot.jobs.yml` host fields flipped →idc03 for the 8 moved jobs so re-renders don't push units back to dell.
   - Watch: `mha-state-push` still running on dell but targets `127.0.0.1:8124` (michael-dev left for idc03 on 10-09) — likely silently dead, audit before moving. Stale-writer audit list: `chaba-cached-videos`, `wp-cam-snapshot`, `yomi-update-all`, `chaba-cms-regen`, `chaba-standard-drift`, `daily-brief` — jobs that may write via the frozen mirror path.
   - Caddy on idc02 is a podman container (`--network=host`); `caddy reload` doesn't reach admin API inside — `systemctl --user restart caddy-edge` applies config (~2s blip).
4. **Backups/offload → idc02** — mddb-standby-pull + rclone remotes. Gate: next scheduled pull lands + gdrive verify.
5. **LAN group → omen** — rsync HA configs + go2rtc + cams last (most user-facing). tony-ha serve re-point. Gate: automations fire, a device toggles, camera streams.
6. **Verify 48h on migrated state** → then dell goes dark for hardware work.
7. **Post-hardware**: decide per service — stay migrated (recommended: dell becomes capacity/failover, not the everything-box again) or pull specific services back.

**Every phase's exit gate includes:** re-measure + update `docs/ssot/infrastructure/ssot.host-capacity.yml` (host roles, headroom, placement bias) — the registry stays true during the migration, not after.

## Per-service state manifest pattern

Every migrated unit needs 4 declared facts in the runbook card / unit comment: `{data_dirs, unit_file, secrets_env, front_name}` — that's the difference between "a migration" and "a system that can migrate." Add as you move each one; don't try to enumerate all 50 upfront.

## Rollback

Every flip is a proxy upstream line + a `systemctl start` on dell (which stays up until step 6). Rollback = flip back. No destructive step before step 6's verify window.

## Risks

- 152-ref repoint: automate the grep→sed but review generated-path URLs (some are examples/docs, don't blind-sed).
- Two-writer window: kanban-commit MUST be stopped on dell before idc03's starts — overlap = diverging card files.
- Secrets/envs aren't in repo — pull from `~/.config/secrets/` per service; don't commit them.
- Omen becomes single-point for LAN control while dell is out — acceptable for days, worth a note.
