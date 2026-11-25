# camwall — retired app restore runbook

Card: `camwall-retire-to-wiki` (MED-1311). Tony 2026-11-09: stop camwall,
migrate documentation here for later restore.

**Status: PHASE 2 EXECUTED 2026-11-25 — option (b) ada-snapshot-only, with
one necessary deviation** (dispatch `dispatch-wt-20261125-012443`, mn01).
Tony answered the Phase-1 request with `ada-snapshot-only`
("Keep Ada snapshot fallback only").

**Deviation from the literal option text:** the option said "stop
CMS/edge/route/vcast/roster-audit", but ada-voice `stale_snapshot()` and
`screens._camwall_fallback()` fetch thumbs over HTTP via
`ADA_CAMWALL_BASE` (default `https://tony-dell.taila0626a.ts.net/apps/camwall`)
→ web Caddy → `camwall-edge :8380` → `~/.local/share/camwall/data`. Stopping
edge+route outright would have killed the very fallback Tony chose to keep.
Executed instead: **the data plane survives end-to-end** —
`cam-wall-pull-vps` (idc02+idc03) → `camwall-edge` (:8380, both hosts) →
narrowed route `/apps/camwall/data/*` only. Everything else retired.

### What was stopped/disabled (live, verified 2026-11-25)

| Host | Action |
|---|---|
| idc03 | `cam-wall-cms-vps.timer`+`.service` disable --now (CMS publishing dead) |
| idc02 | `camwall-render-check.timer`+`.service` disable --now |
| tony-omen | `cam-wall-cms.timer`, `cam-wall-cms-kk.timer`, `cam-wall-roster-audit.timer` (+services) disable --now — all three were LIVE there |
| tony-dell | already parked/disabled before this run (cms/cms-kk/roster `.parked`, pull disabled) — verified, no action needed |

### What was kept running (the ada-snapshot-only plane)

- `cam-wall-pull-vps.timer` on **idc02 + idc03** (30s; OWN/PUSH lane split —
  idc02 owns rama9,traffic,burapha,chonburi,dohweb; idc03 owns
  tony-house,vms-noble-club,vms-noble-a; each rsync-pushes to the peer so
  both edge data dirs are complete). **Do NOT enable cam-wall-pull on
  tony-dell** — it has empty CAMWALL_OWN = all zones and would race the VPS
  manifests; its data dir has been stale since 2026-10-05.
- `camwall-edge.service` quadlets on **idc02 + idc03** (:8380, serves
  `~/.local/share/camwall` ro). idc01 stays masked standby.
- Route narrowed to `/apps/camwall/data/*` → edge (repo
  `ssot.routes.yml` + `stacks/web/Caddyfile`; applied live on tony-dell
  `web` container and idc02 `web-srv` — see "live apply" below).
- input-bridge `/camwall` GET+POST **left in place** — pull-vps reads it
  for zone enable/state, ada `_camwall_fallback` reads it for the zone
  list, and `cctv_wall` zone-enable still works (it only controls which
  thumbs refresh — useful for keeping the fallback fed).
- `zones.yml`, all data dirs, `~/.config/camwall.env`,
  `~/.ssh/camwall-push`, `~/.venvs/camwall` — kept per spec.

### What retired (surface)

- Wall UI: `public/apps/camwall/{index.html,tour-th001.html}` deleted;
  `/apps/camwall/` and non-`/data/` paths now 404.
- CMS publishing: all cam-wall-cms* timers stopped fleet-wide (kk lane was
  already dark since OPS-0749). Existing `camwall-*`/`cam-*`/`cctv-walls`/
  `dvr-wall` pages in MDDB `ada-cms-pages` are now stale snapshots — left
  in place (point-in-time content; HA dashboard tabs + nest tiles keep
  showing last state).
- vcast wall casting of camwall pages — dead (page 404s).
- `ci.camwall-smoke` quality gate + `.github/workflows/camwall-smoke.yml`
  removed; `chaba-audit` camwall probe re-pointed at
  `/apps/camwall/data/zones.json`; `ssot.audit.hosts.yml` expected-unit
  lists updated (dell cms+roster, idc03 cms-vps, idc02 render-check
  removed; edge+pull-vps kept).
- `ssot.apps.camwall.yml` marked PARTIALLY RETIRED.

### Live apply notes (for the verifier)

- tony-dell `web` container: single-file bind-mounted Caddyfile — `caddy
  reload` reported "config is unchanged" (stale inode after git checkout
  replaced the file); fixed by patching
  `~/CascadeProjects/chaba-tony-dell/stacks/web/Caddyfile` +
  `systemctl --user restart web.service`, then `git checkout --` restored
  the mirror file. Container now runs the narrowed config in memory; the
  mirror file still has the OLD block on disk until the next
  served-mirror sync delivers the repo version — **after that sync, run
  `systemctl --user restart web.service` on tony-dell once** so the
  on-disk and in-memory configs agree (or it keeps running narrowed
  either way — both configs serve /data/*; only difference is non-data
  paths, which the old config would re-widen).
- idc02 `~/web-srv/caddy/Caddyfile` patched in place (backup
  `Caddyfile.bak-camwall-retire-20261125`) + `podman exec web caddy
  reload` — verified live (non-data 404, /data 200). Static wall files
  moved to `~/web-srv/public/apps/camwall-retired-bak/`.
- web-srv-sync rsyncs `public/` WITHOUT `--delete` — repo deletions of
  `public/apps/camwall/*` will NOT propagate to idc02 web-srv; the manual
  move above covers it. tony-dell mirror is a git checkout so deletions
  DO propagate via git-safe-pull.

Do NOT delete data dirs or `zones.yml` — unchanged.

## What camwall is

CCTV/traffic camera "walls": a 30s puller refreshes last-good JPEG thumbs +
status cards + manifests per zone; a 15min CMS generator publishes
`camwall-*`/`cam-*`/`dvr-wall`/`cctv-walls` pages into MDDB
`ada-cms-pages` (+ `ada-cms-pages-kk` public-only lane); caddy quadlets on
idc02/idc03 serve the thumbs on tailnet `:8380`; the web tier proxies
`/apps/camwall/*` to them; the input-bridge `/camwall` endpoint is the
control plane (zone enable + settings, persisted `camwall.json`).

Canonical contract doc (still live until retirement lands):
`docs/ssot/apps/ssot.apps.camwall.yml`. Zone SSOT:
`scripts/cam-wall/zones.yml` (group: private|public is the privacy
boundary; `CAMWALL_ZONE_GROUPS` filters publish lanes).

## Consumer map (Phase 1, verified against repo 2026-11-24)

### Producers — stop/disable candidates

| Unit / thing | Host | Definition |
|---|---|---|
| `cam-wall-pull.timer` + `.service` | tony-dell | `systemd/cam-wall-pull.{timer,service}` — 30s, `~/.venvs/camwall/bin/python3 …/chaba-tony-dell/scripts/cam-wall/cam-wall-pull.py` |
| `cam-wall-pull-vps.timer` + `.service` | idc02, idc03 | `systemd/cam-wall-pull-vps.*` — `EnvironmentFile=~/.config/camwall.env`, `CAMWALL_OWN`/`CAMWALL_PUSH` lane split (peer rsync via `~/.ssh/camwall-push`) |
| `cam-wall-cms.timer` + `.service` | tony-dell | `systemd/cam-wall-cms.*` — 15min → `ada-cms-pages` |
| `cam-wall-cms-vps.timer` + `.service` | idc02, idc03 | `systemd/cam-wall-cms-vps.*` — `CAMWALL_DATA=~/.local/share/camwall/data` |
| `cam-wall-cms-kk.timer` + `.service` | tony-dell (RETIRED per OPS-0749; never armed elsewhere — kk lane already dark) | `COLLECTION=ada-cms-pages-kk`, `CAMWALL_ZONE_GROUPS=public` |
| `camwall-edge.service` (caddy quadlet, tailnet :8380) | idc02, idc03 (idc01 masked warm-standby) | `stacks/services/camwall-edge/`, `stacks/idc03/camwall-edge/`, `stacks/idc01/camwall-edge/` |
| `cam-wall-roster-audit.timer` | tony-dell, tony-omen | no unit file in `systemd/` — live def on hosts / ssot.jobs; imports `cam-wall-pull.py`, hard-dep on relay `/camwall` |
| `camwall-render-check.timer` | idc02 | no unit file in `systemd/`; runs `stacks/web/input-bridge/wall-render-check.mjs` |
| `wp-cam-snapshot.timer` (job `wp-cam-snapshot`) | tony-dell | `systemd/generated/tony_dell/wp-cam-snapshot.*` → `scripts/cam-wall/cam-snapshot-wp.py` — **independent** (go2rtc→WP cam CPT); decide separately, default KEEP |
| `wall-render-check.mjs`, `gev-cast-verify.mjs`, `vcast-flap-check.mjs` | idc02 (render-check timer) | check scripts in `stacks/web/input-bridge/` — retire/adjust with route |

### Live readers — break or go stale when producers stop

- **Web route**: `Caddyfile` `handle_path /apps/camwall/*` →
  `100.102.134.91:8380` + `100.123.163.11:8380` least_conn
  (`stacks/web/Caddyfile:410-419`); `ssot.routes.yml` camwall route +
  `camwall-idc02/03` listeners; `stacks/web/public/apps/routes.json`.
- **Static page**: `stacks/web/public/apps/camwall/index.html` +
  `tour-th001.html`.
- **`eye` app**: `stacks/web/public/apps/eye/eye.js` `?src=snap:<zone>/<key>`
  polls `/apps/camwall/data/<zone>/<key>.jpg` — those links 404 after stop.
- **input-bridge `/camwall`** (`stacks/web/input-bridge/server.mjs:756-843`,
  state `VCAST_CAMWALL` → `/data/camwall.json`): read by pull/cms/
  roster-audit/index.html settings; POSTed by Ada `cctv_wall` and
  roster-audit. `vcast-auto-health.py` lease probe GETs it — remove that
  block or the health check false-alarms.
- **vcast wall casting**: camwall pages are cast targets (gev-cast-verify
  `WALL_URL`, runbooks `eye-cast.md`, `vcast-gev-verify-after-act.md`).
- **CMS pages** (MDDB `ada-cms-pages`, ~8 camwall areas ×2 langs + ~85
  `cam-*` dossiers + `cctv-walls`/`dvr-wall`): read by Ada `cms_read`/
  `page=` sends, **HA dashboard tabs** (`ssot.home-assistant.instances.yml`
  `#/cctv-walls`, `#/camwall-traffic`), **chaba-nest dashboard tiles**
  (`ssot.chaba-nest-dashboard.yml`). Pages embed thumb URLs → broken
  images after edge dies; pages themselves are point-in-time.
- **Ada (ada-voice repo, NOT in this worktree)**: `backend/vms_camera.py`
  `stale_snapshot()` reads camwall manifests/thumbs as fallback for
  `ada_camera_snapshot`; `cctv_wall` tool POSTs `/camwall`; `ADA_CAMWALL_BASE`
  env; PWA/CMS sidebar reads `data/zones.json`. **Must be mapped in the
  ada-voice repo before stopping** — this worktree only has `.patch` files.
- **Audits/CI**: `scripts/audit/chaba-audit.py` probes
  `/apps/camwall/`; `scripts/audit-edge-upstreams.py` parses
  `~/.config/camwall-edge/Caddyfile`; `ssot.audit.hosts.yml` expected
  units/timers (tony-dell: cam-wall-cms.timer, cam-wall-roster-audit.timer;
  idc03: camwall-edge.service, cam-wall-pull-vps.timer, cam-wall-cms-vps.timer,
  + known_failed cam-wall-pull-vps.service; idc02: camwall-edge.service,
  cam-wall-pull-vps.timer, camwall-render-check.timer); `ssot.quality.yml`
  `ci.camwall-smoke` + `.github/workflows/camwall-smoke.yml`; `ssot.cms.yml`
  IA prefix rules; `scripts/ada/cms-ia-normalize.py` cctv domain rules;
  `scripts/ops/secrets-collect.sh` + `stacks/idc03/secrets-backup` sweep
  `~/.config/camwall.env`.
- **zones.yml consumers**: pull + cms (`zone_meta.py`); ada-voice PWA/CMS
  sidebar reads propagated `data/zones.json`/page meta (external repo).

### Explicitly INDEPENDENT — do not stop with camwall

- **mn01 `vms-snap.py:8377`** (`stacks/services/xmeye-vms/`) — shared shim;
  other consumers: ada-voice `ada_camera_snapshot` live path,
  `/apps/vms-snap` Caddy route, `eye.js ?src=vms:<ch>`.
- **`traffic-snap.py:8378`** (`stacks/services/traffic-cam/`) — same
  `/snap?ch=` contract, cam-wall-pull never calls it.
- **`wp-cam-snapshot`** job (above).
- `cam-frame-refresh`, `ipcam65-*` units — unrelated.

### Data / config locations (KEEP — do not delete)

- `scripts/cam-wall/zones.yml` — zone SSOT (repo).
- `scripts/cam-wall/data/` is NOT a thing; thumbs live at:
  - tony-dell: `~/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/camwall/data/`
    (CAMWALL_DATA default, gitignored)
  - idc02/idc03: `~/.local/share/camwall/data/` + `~/.local/share/camwall/yolov8n.onnx`
- `~/.config/camwall.env` on idc02/idc03 (and collected fleet-wide) —
  `CAMWALL_OWN`, `CAMWALL_PUSH`, upstream creds.
- `~/.config/camwall-edge/Caddyfile` on edge hosts.
- input-bridge state `camwall.json` (`/data/camwall.json` in quadlet,
  `~/.local/share/input-bridge/camwall.json` default).
- `~/.ssh/camwall-push` keypair + `camwall-*` ssh aliases (CAMWALL_PUSH rsync).
- `~/.venvs/camwall/` venv on tony-dell.

## Stop checklist (Phase 2 — EXECUTED under option b; kept items noted)

Per host — verify live state first (`systemctl --user list-timers`,
`podman ps`), repo is intent not truth. Items struck through / marked
[KEPT]/[DONE] reflect the 2026-11-25 execution; unmarked items remain for
a future full-stop decision.

1. **tony-dell** [DONE — was already parked/disabled]: cms/cms-kk/
   roster-audit `.parked`, cam-wall-pull disabled. [KEPT disabled]
   cam-wall-pull — VPS lane owns production; dell pull has empty
   CAMWALL_OWN and would race manifests. Keep data dir + zones.yml.
2. **idc02** [DONE: camwall-render-check disabled] [KEPT:
   cam-wall-pull-vps.timer + camwall-edge.service — the ada snapshot
   data plane] [n/a: no cms-vps units installed on idc02].
3. **idc03** [DONE: cam-wall-cms-vps disabled] [KEPT:
   cam-wall-pull-vps.timer + camwall-edge.service].
4. **tony-omen** [DONE: cam-wall-cms.timer, cam-wall-cms-kk.timer,
   cam-wall-roster-audit.timer all disabled — they were live].
5. **Web tier** [DONE differently]: route NARROWED not removed —
   `/apps/camwall/data/*` still proxies to edge (required by ada
   stale_snapshot); non-data paths 404. Static UI files deleted in repo;
   live copies moved aside on idc02 web-srv. `camwall-idc02/03`
   listeners kept (edge still serves).
6. **input-bridge** [KEPT]: `/camwall` endpoint left fully in place —
   pull-vps zone gating + ada `_camwall_fallback` zone list + cctv_wall
   zone-enable all still read/write it.
7. **Checks** [DONE]: chaba-audit probe → /apps/camwall/data/zones.json;
   ssot.audit.hosts.yml updated; camwall-smoke workflow + quality entry
   retired. [KEPT] vcast-auto-health probe_lease (endpoint still live),
   audit-edge-upstreams camwall-edge candidate (edge still live),
   tests/camwall/* (scripts kept for restore).
8. **CMS pages** [DONE — left stale]: pages remain in ada-cms-pages as
   point-in-time snapshots; no archive run. Dashboards keep last state.
   Ada cms-ia-normalize rules stay harmless.
9. **Secrets/ssh** [KEPT]: camwall.env still REQUIRED (pull-vps
   EnvironmentFile) — stays in secrets-collect/backup. camwall-push
   keypair still in use by the OWN/PUSH lane.
10. **Docs** [DONE]: ssot.apps.camwall.yml marked PARTIALLY RETIRED with
    pointer here.

## Restore steps (full)

1. Repo: `git revert`/reland the retirement commit(s); units live in
   `systemd/` — reinstall per host drop-in dir (`~/.config/systemd/user/`).
2. Hosts: `systemctl --user enable --now` the timers above; unmask +
   `--now camwall-edge.service` on idc02/idc03 (quadlet files kept parked);
   idc01 stays masked unless DR role returns.
3. Env: `~/.config/camwall.env` (CAMWALL_OWN/PUSH) must still exist — it
   was kept; recreate from secrets-backup age snapshot if lost
   (`stacks/idc03/secrets-backup/`).
4. Caddy: re-add `handle_path /apps/camwall/*` block + routes.json +
   ssot.routes.yml entries (git history has exact lines).
5. Data: thumbs/manifests regenerate on first pull cycles; historical
   `detections-*.jsonl` and old thumbs survive in the kept data dirs.
6. CMS: pages republish on next 15min cms timer; kk lane needs explicit
   re-arm decision (was already retired pre-camwall-retirement).
7. input-bridge: restore `/camwall` handlers + `VCAST_CAMWALL` env if the
   revert didn't cover them.
8. Ada side: `ADA_CAMWALL_BASE`, `stale_snapshot`, `cctv_wall` live in the
   ada-voice repo — restore there independently; camwall data being
   present is sufficient for the fallback path.
9. zones.yml: never deleted — `scripts/cam-wall/zones.yml` in repo.
10. Verify: wall page loads, manifest fresh, cms pages update, eye
    `snap:` links resolve, `chaba-audit` camwall probe (if restored to
    audit list) green.
