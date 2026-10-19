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
   - ✅ 2026-10-17 batch 2: `websockify-macbook` (tailnet-IP bind :6080), `websockify-vms-mn01` (:6082), `mcp-link-monitor`, `notebooklm-rest`+`notebooklm-mcp` (podman save→load, quadlets, tailnet+loopback :3011) → idc02; `overnight-assessment` job → idc03 (was failing nightly on frozen checkout). `ssot.jobs.yml` host fields flipped →idc03 for the 8 moved jobs so re-renders don't push units back to dell.
   - **Zombie found+fixed:** dell's `michael-dev.service` was still *running* (container restart reanimated it 10-16) — `mha-state-push` had been feeding the stale duplicate for a week while the real michael-dev (idc03) got nothing. Dell instance masked (symlink→/dev/null); `mha-state-push` now on idc03 (venv `~/.venvs/mha-push`, tokens copied), mirroring 60 entities live. Quadlet units aren't disable-able — park `.container` files in `~/.config/containers/systemd/migrated-off/`.
   - Stale-writer audit list: `chaba-cached-videos`, `wp-cam-snapshot`, `yomi-update-all`, `chaba-cms-regen`, `chaba-standard-drift`, `daily-brief` — jobs that may write via the frozen mirror path.
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

## Phase 3 batch 3 (2026-10-18): helm + bserver → idc02

- **bserver** (CMS: `/`, `/new`, `/decisions`, `/infrastructure`) → idc02 podman
  `bserver:latest` (34.7M, ID 7c783ac77999), binds tailnet IP :8092 + :8443
  (was wildcard on dell). Static mount `stacks/web/bserver-www` comes via the
  chaba checkout — no data copy needed.
- **helm** (`/apps/helm`) → idc02 podman `web-helm:prod` (947M), tailnet :3003.
- **Gotcha — `podman save` multi-tag quirk**: saving `web-helm:prod bserver:latest`
  in one archive landed BOTH tags on the helm image ID on the receiving host.
  Always `podman save` one ref per archive (or verify IDs after load). bserver
  was retransferred solo.
- **Gotcha — quadlet `AddHost` unsupported on podman 4.9**: dell runs newer;
  on idc02 use `PodmanArgs=--add-host host.docker.internal:host-gateway`.
- Dell quadlets parked (`*.container.parked`) — same pattern as notebooklm.
- Verified: `/`, `/decisions`, `/infrastructure`, `/apps/helm` → 200 via dell edge.

## Phase 4 preview — mddb backup chain (2026-10-18)

- **Found broken**: `chaba-postgres-16` on dell had been down ~25h (status 125,
  restart-counter exhaustion) — collateral of the 10-16 freeze window. yomi-api
  degraded, yomi timers + trade DB dead. Restarted clean; 22 tables intact;
  all yomi jobs re-verified OK.
- **`mddb-standby-pull` retired on dell** (disabled). Its three roles:
  pull newest → covered by idc02 `mddb-lab-pull` (daily, succeeds);
  standby replica → idc02 `mddb-lab` (:11024) + `mddb-ops` (:11025);
  gdrive tier → NEW `mddb-gdrive-tier.timer` on idc02 (04:30 daily,
  newest-2 local, rclone → gdrive:backups/mddb/).
- Dell disk relief: stranded 8.2G filecopy pushed to gdrive (14G free, 89%).
- idc02 had 38G untiered mddb backups accumulating — the new tier job drains
  them to gdrive on first run.
- Canonical units: `systemd/mddb-gdrive-tier.{service,timer}`.

## Repair — chaba.h3 publish chain (2026-10-18)

- `cms-h3-publish` + `mcp-debug-h3-sync` failing since ~10-14: `git push`
  remote unpack failed — **corrupt tree object** in the object store
  (dell disk-full writes). 2016 unpushed auto-commits.
- The `chaba-h3-tony-dell` checkout is a **linked worktree of the served
  checkout** — they share `.git/objects`. Served master verified healthy
  (mirror pull + rev-parse clean); corruption confined to the h3 chain.
- Fix: `git update-ref refs/heads/chaba.h3 origin/chaba.h3` — abandoned the
  corrupt local chain (auto-publish output, regenerable). Both jobs push
  clean again.
- **Migration note**: the h3 worktree + its publisher jobs write branch
  `chaba.h3` through dell's served-checkout object store — belongs in the
  writer-constellation move to idc03, not a standalone port.

## Hardening — parked ALL migrated dell unit files (2026-10-18)

- `chaba-board-api` on dell was manually re-started (systemd user unit,
  no parent chain — an ssh session did `systemctl --user start`) and ran
  ~1.5h writing to the FROZEN checkout. Disabled isn't enough — unit files
  can be re-started by anything.
- **Procedure update**: after migrating a service, don't just stop+disable —
  rename unit files to `*.parked` (same convention as quadlets). Parked 42
  files: whole writer family + migrated services + retired zombies.
- Dell running service count now ~35 real services (from ~75 at start).

## Constellation plan — postgres + yomi + trade → idc03 (drafted 2026-10-19)

One coupled move. `chaba-postgres-16` serves `chaba` (168M, yomi) + `trade`
(77M, mostly empty) DBs. Consumers resolve `postgre` via baked `--add-host`
in unit ExecStart (dnsmasq-postgre only serves LAN/floating name lookups).

Steps:
1. `pg_dump` chaba + trade on dell (~245M total — trivial).
2. Recreate `chaba-postgres-16` on idc03 (same unit; bind loopback +
   `100.102.134.91:5432`); restore dumps.
3. rsync `~/.local/share/yomi` (22M) + `~/.yomi` (174M) + `~/.config/yomi/*.env`;
   install yomi-* units on idc03 with `--add-host postgre:100.102.134.91`.
   yomi-api keeps tailscale-serve :3000 (serve on idc03, not dell).
4. trade-api: `podman save localhost/trade-trade-api:latest | ssh idc03 load`
   (LOCAL BUILD — one ref per archive); rsync `~/CascadeProjects/trade/`
   (data+config+.env mounts); bind `127.0.0.1:9002`; serve :9002 on idc03.
5. LAN client 192.168.2.67: app sees it via XFF through the dell web edge —
   flip `/apps/trade/api/*` + `/api/ws/*` upstream to `100.102.134.91:9002`;
   LAN path preserved. (If a direct :9002 tailnet consumer exists, keep a
   dell-side TCP forwarder temporarily.)
6. dnsmasq-postgre: repoint `address=/postgre/` → 100.102.134.91 during
   transition; retire the unit once nothing queries it.
7. Verify pg conns, yomi /health, trade routes; park dell units.

Not done yet — needs a quiet-ish window (trade has a live client) and a
fresh capacity check on idc03 before landing the pg + node workload.

## Phase 4b — pg+yomi+redis+trade constellation → idc03 (DONE 2026-10-19)

Executed the plan above in one window:
- pg_dump both DBs (8M compressed) → `chaba-postgres-16` rebuilt on idc03,
  bound tailnet-only `100.102.134.91:5432` (idc03's loopback :5432 is
  litellm's — untouched). 22 tables restored, counts match dell.
- **redis had been dead on dell ~3 days** (same Oct-16 crash as pg —
  yomi degraded to cache-miss silently). Rebuilt on idc03 tailnet-only;
  yomi-api logs `Redis connected` again.
- yomi-api + 4 timers moved; needed `@google/generative-ai` which dell
  had ad-hoc at checkout root (NOT in package.json — repo gap, fixed by
  installing on idc03; package.json still lacks it).
- trade-api image transferred solo (one-ref-per-archive rule); health
  identical to dell's incl. pre-existing 17-day-stale FX (not migration).
- Edge flips: `/api/yomi/*` → :3000, `/apps/trade/api*` + `/api/ws/*` →
  :9002 on idc03. Verified 200 through dell edge.
- **Route-shadow bug (pre-existing since 10-17):** Caddy sorts `/api/*`
  BEFORE `/api/yomi/*` and `/api/ws/*` in the handle table — the
  status-data catch-all answered both with its FastAPI 404 since it
  landed. Fix: catch-all matcher now excludes both prefixes (0951a45e5).
- dell units all parked (.service/.timer.parked): yomi-api, 4 yomi
  timers, trade-api, chaba-postgres-16, redis. tailscale serve
  :3000/:9002 removed on dell, added on idc03.
- dnsmasq-postgre repointed `postgre` → 100.102.134.91 (kept — LAN
  consumers may still resolve it).
- ssot.jobs.yml: yomi-backup/update-all/update-active host → idc03.
- Dell WAN/LAN dropped ~17:00 during the cutover (gateway 192.168.1.1
  stopped ARPing; tailscale held then dropped). Verified after return.
