# Chaba Session Modes

At the start of every session, determine the active operational mode using this precedence:

1. `DEVIN_MODE` environment variable.
2. `~/.config/devin/config.json` → `mode.current`.
3. `.devin/config.local.json` → `mode.current`.
4. `.devin/config.json` → `mode.current`.
5. Default to `normal`.

Then follow the behavior for that mode in `docs/ssot/infrastructure/ssot.devin-modes.yml`.

Valid modes: `normal`, `plan`, `build`, `review`.

# Agent Quick Reference - Home Assistant

## Entry points

- Instances SSOT: `docs/ssot/infrastructure/ssot.home-assistant.instances.yml`
- Dashboard SSOT: `docs/ssot/infrastructure/ssot.home-assistant.dashboards.yml`
- Entities SSOT: `docs/ssot/infrastructure/ssot.home-assistant.entities.yml`
- Cards SSOT: `docs/ssot/infrastructure/ssot.home-assistant.cards.yml`
- Design SSOT: `docs/ssot/infrastructure/ssot.home-assistant.design.yml`
- How-to/runbooks SSOT: `docs/ssot/infrastructure/ssot.home-assistant.howto.yml`
- MCP/auth SSOT: `docs/ssot/infrastructure/ssot.home-assistant.mcp.yml`
- Long-form PF3 runbook: `docs/kb/home-assistant/pf3-runbook.md`

## Key URLs

- tony-ha: `https://tony-dell.taila0626a.ts.net:8123` (tailnet only — HA binds loopback; no LAN/plain-HTTP access)
- michael-dev: `http://127.0.0.1:8124` / `https://tony-dell.taila0626a.ts.net:8124`
- michael-ha: `http://michael-ha:8123` / `https://nupo4ndqdqydt78zmpq0z5wzp1bdrqgs.ui.nabu.casa/`
- tony-test views: `https://tony-dell.taila0626a.ts.net:8124/tony-test/{pf3,pf4,pfg,pfg1,pfg2,tpl,data}`

## Token files

- michael-dev: `~/.config/secrets/ha-michael-dev.env` (`HASS_TOKEN`)
- michael-ha: `~/.local/share/home-assistant-michael/ha-token` (raw token file, NOT `ha-michael-live.env`)
- Never paste tokens into chat or commit them.
- The `michael-dev` token in `~/.config/secrets/ha-michael-dev.env` is valid and works for REST (verified 2026-09-04).
- Tailscale SSH (`ssh tony-dell`) periodically requires a browser auth check; it prints a `login.tailscale.com/a/...` link — ask the user to open it, then retry.

## Deployment policy

- **Never auto-deploy from michael-dev.** Building and previewing on `michael-dev` is fine, but deploying or promoting the bundle/dashboard to `michael-ha` or `tony-ha` requires explicit user approval in the same session.
- `deploy-card.sh` is dev-only by default; use `promote-michael.sh` or `promote-tony.sh` for live hosts.
- Even if `tony-ha` runs on the same machine (`tony-dell`), copying a bundle or resource to it is a deploy and must be approved.

## Build / deploy commands

- Build card: `cd /home/tony/CascadeProjects/sunsynk-power-flow-card && npm run build`
- Typecheck before trusting the bundle: `npx -p typescript tsc --noEmit` (the rollup build uses Babel and does NOT type-check)
- Restart michael-dev: `ssh tony-dell 'systemctl --user restart michael-dev.service'`
- Restart michael-ha: `ssh michael-ha 'ha core restart'`
- Deploy card bundle to dev: `./scripts/home-assistant/deploy-card.sh` — builds, derives the next version from michael-dev's `lovelace_resources`, scp's, restarts, verifies HTTP 200.
- Promote dev bundle/views to michael-ha: `./scripts/home-assistant/promote-michael.sh --views g1,g2,tpl` (requires explicit user approval)
- Promote dev bundle/views to tony-ha: `./scripts/home-assistant/promote-tony.sh --views g1,g2,tpl` (requires explicit user approval; seed the resource on first run).
- Push dashboard config live (no restart): `python3 scripts/home-assistant/push-dashboard.py <ha_url> tony-test --mutate /tmp/mutate.py` (dev: `source ~/.config/secrets/ha-michael-dev.env`; ha: `HASS_TOKEN=$(cat ~/.local/share/home-assistant-michael/ha-token)`)
- Apply a TPL template onto a view tile: `python3 scripts/home-assistant/apply-tpl.py <ha_url> tony-test tpl pfg2 --map "Title:r,c;..."` (does NOT copy pfg_spans; add `--dry-run` to preview)
- Sync live dashboard into repo: `./scripts/home-assistant/sync-ssot-from-live.sh`
- Sync SSOT to MDDB: `python3 scripts/sync-ssot-to-mddb.py`
- Validate all SSOT: `node scripts/ssot-validate-all.mjs`

## Common tasks

- Dashboard config changes (card layout, lines, images — anything already supported by the bundle): mutate live via `push-dashboard.py` over websocket, then `sync-ssot-from-live.sh`. No rebuild or restart needed; HA refreshes Lovelace automatically.
- Copy a whole view between instances (parity): read it from dev's `lovelace/config`, replace in ha's config, `lovelace/config/save`. On michael-ha, re-add `card_mod` to the pfg2 card after every view copy (the visionos theme injects a frosted-glass `ha-card::before`; the copy from dev drops the override).
- michael-dev parity entities: `packages/a_dev_mocks.yaml` has `dev_*` helpers AND `mha_mirror_*` REST sensors that live-mirror real michael-ha entities on the same entity_id (tze200_*, washer power). Prefer those mirrors over new mocks — same entity IDs mean identical dashboard config on both hosts.
- Reorder or add a tab: prefer `push-dashboard.py` websocket mutate; `.storage` edits directly require an HA restart to take effect.
- Fix SVG text overlay: check `Battery*_SOC` `<svg>` display condition in `src/components/compact/bat/bat-elements.ts` so plain text hides when combined `{target}% | {current}%` is visible.
- Verify visually: use a logged-in Chrome profile or browser dev tools on the card shadow root.
- Guard against bundle drift: `sync-ssot-from-live.sh` picks the newest `www/` bundle by version. Remove obsolete `sunsynk-power-flow-card-fork-v*.js` bundles or cross-check `lovelace_resources` before committing.

## Parallel-session rules (added 2026-09-06)

Parallel sessions caused real breakage: duplicated `pfg2-card.ts`, undeclared `valueLabel` render crash, version races. Follow these rules:

1. **Worktree per session** for card-repo code changes — never edit `/home/tony/CascadeProjects/sunsynk-power-flow-card` directly when another session may be active:
   ```bash
   git -C /home/tony/CascadeProjects/sunsynk-power-flow-card worktree add \
       /home/tony/CascadeProjects/sunsynk-wt-<feature> -b <feature>
   ```
   Merge to `main` only after `npm run build` passes in the worktree. Deploy from `main` only.
2. **Deploy lock** — `deploy-card.sh` uses `flock /tmp/pfg-deploy.lock`; concurrent deploys are refused. Do not bypass it.
3. **Dashboard pushes** — whoever runs `push-dashboard.py` must run `sync-ssot-from-live.sh` immediately after, then commit. The live dashboard is a shared resource; unsynced mutations are the main source of drift between sessions.

## Current state (2026-09-09)

- Active card bundle: `v207` on michael-dev; `v206` on michael-ha and tony-ha. Per-host counters; verify parity by md5, not version.
- Chart code is modularized under `src/cards/pfg/` (registry + `chartOverlayStyle` + per-type files in `charts/` plus `pfg3d-loader.ts` and `pfg3d-chart.ts`). `pfg-shared.ts` is gone — update imports to `./pfg`.
- 3D charts (`surface3d`/`bar3d`) are now rendered by a reactive `<pfg-3d-chart>` custom element: incremental hourly-statistics refresh, camera state preserved on updates, and observers/listeners cleaned up on disconnect.
- `deploy-card.sh` is dev-only; live promotion uses `promote-michael.sh` (michael-ha) and `promote-tony.sh` (tony-ha) and requires explicit user approval.
- echarts/echarts-gl are vendored at `/local/echarts-5.5.1.min.js` + `/local/echarts-gl-2.1.0.min.js` on both hosts; `surface3d`/`bar3d` try local first, CDN fallback.
- 3D chart lessons (G1 surface3d / G2 bar3d): use `xAxis3D.type: 'category'` + `data` order for hour axes — `inverse` on a `value` axis is ignored by ECharts GL. See `pfg_3d_charts` runbook in `docs/ssot/infrastructure/ssot.home-assistant.howto.yml`.
- History/accumulating charts share the localStorage incremental cache policy (`data_cache_policy` in `ssot.home-assistant.design.yml`).
- michael-ha credentials: API/websocket token = `~/.config/secrets/ha-michael-live.env` (the `ha-token` file was refreshed to the same value 2026-09-08); UI login = `~/.local/share/home-assistant-michael/credentials.json` (`nakva`).
- michael-ha sidebar verified visually: Overview, Dossier, Map, Tony test + built-ins (Energy/Activity/History/File editor/HA-MCP/HACS/Matter Server/Settings/Notifications).
- michael-ha tony-test tabs: `V0 (p0) → V1 (p0-2) → G1 → SK → TPL → juWorkshop → Solar Assistant → glass → Weather`.
- New `/local/` assets may 404 in cached browsers while curl returns 200 — bump the reference `?v=N` in the config (runbook: `stale_local_asset_404` in howto SSOT).
- `apply-tpl.py` gained `--bg` (forces copied charts to `position: "bg"`).
- Dashboard snapshot is `docs/home-assistant/dashboards/tony-test-current.json`.
- Post-restart MCP verification: all 18 configured Devin MCP servers are reachable after tony-dell restart. `michael-dev` and `tony-ha` `ha_mcp_tools` require `_READY_STALL_TIMEOUT_SECONDS=300s` / `_READY_TOTAL_CAP_SECONDS=900s` in `embedded_server.py` to avoid startup timeout on HA 2026.9.0. `github` MCP now uses `~/.config/devin/mcp-scripts/mcp-github-proxy.py`.

## XMEye VMS on tony-dell

- Container: `xmeye-vms-vnc` (Podman, `--cpus 0.5`), exposes VNC on `192.168.2.67:5900` (no password).
- Browser noVNC: `http://tony-dell/apps/vnc/` -> `http://tony-dell/apps/vnc/vnc.html` (noVNC) -> `ws://tony-dell/apps/vnc/ws` (Caddy reverse proxy to `host.containers.internal:6081` -> websockify -> VNC). HTTPS uses `wss://tony-dell.taila0626a.ts.net/apps/vnc/ws` (same Caddy path, TLS via Tailscale). Port 6080 is reserved for `websockify-macbook.service`.
- Websockify: `websockify 0.0.0.0:6081 127.0.0.1:5900` on tony-dell.
- Startup: `rm -f /tmp/.X11-unix/X99` (stale socket cleanup), `Xvfb :99 -screen 0 1280x720x16`, `twm -display :99`, `x11vnc -display :99 -noxkb -forever -shared -rfbport 5900 -nopw -wait 50 -defer 30`, then `cd /app && wine explorer /desktop=VMS,1280x720 VMS.exe`. Use `-shared` so browser reconnects don't get refused.
- VMS login may start as a wireframe; one click in the noVNC window renders it.
- VMS config: `/home/tony/.cache/xmeye-vms/vms-runtime/config.ini`.
- VMS app login: `admin` / `admin` (saved hash `F360C0DD174588FA` in `config.ini` `[Login]` `password`).
- Device/DVR test password supplied by user: `amc123456` (also stored, along with per-DVR cloud IDs/users, in `~/.config/secrets/xmeye-dvr.env`).
- DVRs:
  - `noble-club`: Cloud/Serial ID `d811d82e21d6c031`, user `admin`, pass in `~/.config/secrets/xmeye-dvr.env`.
  - `noble-a`: Cloud/Serial ID `f2ca2dca0bc4ae4fnxjd`, user `advance`, pass in `~/.config/secrets/xmeye-dvr.env`.
- QR files for import (inside the VMS at `Z:\\app\\qr\\`, mounted from `/home/tony/.cache/xmeye-vms/vms-runtime/qr/`):
  - `S__7610372.jpg`
  - `QR.jpg`
  - `qr-noble-a.jpg`
- Set `autologin=true` in `config.ini` after the saved hash is in place to skip the login prompt on next restart.

## GEV Gemini Live voice deployment

Source and build: `/home/tony/gods-eye-view`

- Build: `npm run build` (requires Vite base `/apps/gev/`).
- After every build, patch `dist/assets/index-*.js`:
  - `/api/*` -> `/apps/gev/api/*`
  - `/models/*` -> `/apps/gev/models/*`
  - `msaaSamples:4` -> `/iPad|iPhone|iPod/.test(navigator.userAgent)?1:4`
- Stage to `stacks/web/public/apps/gev/`: `index.html`, `*.svg`, `assets/`, `models/`, `cesium/`.

Infrastructure:

- Caddy serves `/apps/gev/*` from `stacks/web/public/apps/gev/`.
- GEV API proxy: `gods-eye-view-api` on `127.0.0.1:4173` via Caddy `handle /apps/gev/api/*`.
- Gemini bridge: `gev-gemini` on `ws://127.0.0.1:8789` proxied to `/apps/gev-live/ws`.
- Bridge image: `localhost/gev-gemini:latest` built from `stacks/tony-dell/gev-gemini/`.
- Tool declarations are extracted from `GEV_REALTIME_TOOLS` in `vite.config.js` and written to `stacks/tony-dell/gev-gemini/tools.json`. Gemini Live rejects `additionalProperties` in function-declaration parameters; the bridge strips them recursively.

Voice controller (`src/voice/gevGeminiRealtime.js`):

- Connects to `/apps/gev-live/ws`, captures mic audio as 16kHz PCM mono.
- The `ScriptProcessorNode` input must pass through a `GainNode` set to `1` while recording and `0` while muted; the recording flag alone is not enough.

Service worker / PWA:

- Shared `/apps/sw.js` cache name is `apps-v6`.
- All app pages register `/apps/sw.js?v=6` with scope `/apps/`.
- GEV `index.html` links `/apps/gev/manifest.json`, sets `apple-mobile-web-app-capable=no` for iOS microphone compatibility, and registers the shared service worker.

Test commands:

- Page: `curl -s -o /dev/null -w '%{http_code}' https://tony-dell.taila0626a.ts.net/apps/gev/`
- WS: `python3 -c "import asyncio, websockets, ssl; ..."` against `wss://tony-dell.taila0626a.ts.net/apps/gev-live/ws`
- Text tool call cycle: send `{'type':'text','text':...}`, receive `function_call`, respond with `{'type':'tool_response','responses':[{'id':...,'name':...,'response':...}]}`.

Caveats:

- iOS microphone works in Safari, not in standalone home-screen PWA mode.
- iPad requires `msaaSamples:1` to avoid Cesium WebGL crash.
- Current implementation uses Gemini output transcription text only; no audio playback.

# Devin on tony-dell — crash/runbook (2026-09-12)

## Restart after a crash

tony-dell's display stack (as of 2026-09-18):

- `:1` / vt7 — the **persistent seat**: root Xorg + `xfce-seat.service` (`dbus-run-session -- xfce4-session`, `Restart=always`). This is what Barrier controls. It is NOT the GDM greeter — the greeter lives on tty1 and `barrier-pin-vt.timer` keeps vt7 in the foreground. (`lxqt-seat.service` was the predecessor — disabled 2026-09-18; pin-vt accepts either unit.)
- `:20` — Chrome Remote Desktop's Xvfb session (`startxfce4`), separate and less durable.
- `:99` — headless Xvfb for browser automation.

`devin-desktop` belongs on `:1` (the persistent seat — same model as tony-omen's `:0` console session). Launching it on the CRD `:20` session means it dies when CRD restarts; launching it as a child of xfce4-session means it dies when `xfce-seat` restarts (but the XDG autostart immediately relaunches it — that is the designed lifecycle; a stray ssh-launched instance on the same display produces a SECOND devin process and duplicate windows, so don't launch manually while the seat session is alive).

As of 2026-09-18 there is an XDG autostart entry (`~/.config/autostart/devin-desktop.desktop`), so devin-desktop starts automatically inside whichever desktop session comes up — after a reboot, `linger` → `xfce-seat` → xfce4-session → autostart brings it back on `:1` with no manual step. GDM autologin is intentionally DISABLED: a gdm session on tty2 would steal the foreground VT from the Barrier seat and `barrier-pin-vt` is designed not to steal it back.

`xfce4-session` on the seat needs its own dbus session: the unit wraps it in `dbus-run-session` and unsets `SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS GNOME_KEYRING_CONTROL SSH_AUTH_SOCK` — running bare `xfce4-session` or `startxfce4` under the shared user bus makes the session exit instantly (org.xfce.SessionManager name collision with the CRD session; `startxfce4` also exits immediately which restart-loops the unit).

If devin is missing on `:1`, restart the seat session rather than launching devin by hand (a manual launch races the XDG autostart and produces two devin instances = duplicate windows):

```bash
ssh tony-dell 'systemctl --user restart xfce-seat.service'
```

Manual launch on `:1` is only for when NO desktop session is running (e.g. seat service broken):

```bash
ssh tony-dell 'env DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus nohup /usr/share/devin-desktop/devin-desktop > /home/tony/.local/share/devin/cli/devin-restart-$(date +%Y%m%d-%H%M%S).log 2>&1 </dev/null &'
```

Verify:

```bash
ssh tony-dell 'pgrep -a -f devin-desktop | grep -v "pgrep\|ssh\|tailscaled"'
```

## "Cannot start" but processes exist (learned 2026-09-19)

If devin-desktop processes are running but no usable window appears, check window state before restarting anything:

```bash
ssh tony-dell 'export DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority; \
  xdotool search --class devin-desktop; \
  xprop -id <win> _NET_WM_DESKTOP; xprop -root _NET_CURRENT_DESKTOP; \
  xwininfo -id <win> | grep "Map State"; scrot /tmp/scr.png'  # screenshot shows the truth
```

Two observed variants:

1. **Window on another workspace** — xfwm4 unmaps windows on inactive desktops. `_NET_WM_DESKTOP` ≠ `_NET_CURRENT_DESKTOP`. Fix: `xdotool set_desktop_for_window <win> <current> && xdotool windowactivate <win>`.
2. **Hung renderer (black window)** — window is `IsViewable` and focused but paints solid black; taskbar shows it but it never displays. The renderer is dead; remapping won't help. Restart the instance: `kill <main-pid>` (TERM first), clean leftover children (`pgrep -f devin-desktop`), then relaunch on `:1` with the manual-launch command above. Sessions persist in `sessions.db` — nothing is lost. Careful with `pkill -f` over ssh: the remote shell's own cmdline matches the pattern and kills the session — use explicit PIDs or exclude self.

Also check for a duplicate instance: clicking the launcher while the first instance is alive spawns a second devin-desktop that stalls (only a 10x10 dummy window, no renderer). Kill the duplicate's main PID — do NOT kill the instance that owns the real session window (check `_NET_WM_PID` on the titled window).

## What was observed today

- Installed version: `devin-desktop 3.10.23-1789035177`.
- The main process was not running; five stale `app-devin-desktop-*.scope` units remained, holding orphaned child processes (yolo server, websockify, etc.).
- `~/.local/share/devin/cli/watchdog.log` showed the renderer being killed by the watchdog when CPU stayed above 50% for 10s.
- The last session log ended with `Parent process exited; shutting down ACP server` and was full of `affogato::agent::control_loop: max_trailing_images=1 HTTP 413 Payload Too Large` errors.
- `~/.local/share/devin/cli/sessions.db` is ~2.0 GiB.

## Log locations

- Devin logs: `~/.local/share/devin/cli/logs/devin_YYYYMMDD-HHMMSS_<pid>.log`
- Watchdog log: `~/.local/share/devin/cli/watchdog.log`
- Cleanup log: `~/.local/share/devin/cli/cleanup.log`

## Open problems to watch

- `HTTP 413 Payload Too Large` with `max_trailing_images=1` may return if large screenshots are sent; the Headroom proxy (`http://127.0.0.1:8787`) was not running during this incident.
- If the new `3.10.23` build keeps crashing, the cached `3.9.19-1788908513` deb is available in `/var/cache/apt/archives/` and can be downgraded.

## Ada Pi PWA (learned 2026-09-13)

### Runtime

- Production URL: `https://tony-dell.taila0626a.ts.net/apps/ada_pi/`
- Funnel: enabled (`tailscale funnel --bg --https=443 --yes 127.0.0.1:8085`)
- Caddy on tony-dell: listens on `127.0.0.1:8085`, configured in `~/.config/caddy/Caddyfile.tony-dell`
- Backend: `pwa_server.py` via `~/.config/systemd/user/ada-pi-pwa.service`, running on `0.0.0.0:8001`
- Python venv: `/home/tony/CascadeProjects/ada-pi/.venv`
- API key: from `~/.config/yomi/yomi-api.env` (`GEMINI_API_KEY`) into `~/.config/secrets/ada-pi-pwa.env`
- WebSocket: `wss://tony-dell.taila0626a.ts.net/apps/ada_pi/ws`

### Caddy routing

- `/apps/ada_pi/*` → `127.0.0.1:8001` (strips `/apps/ada_pi` prefix)
- `/apps/home-assistant/*` → `127.0.0.1:8123`
- `/` → `127.0.0.1:80`

### Service commands

- `ssh tony-dell 'systemctl --user {start,stop,status} ada-pi-pwa caddy-tony-dell'`
- `ssh tony-dell 'sudo -n tailscale funnel status'`
- `ssh tony-dell 'sudo -n tailscale funnel --https=443 off'` to disable

### SSOT

- `docs/ssot/apps/ssot.apps.ada_pi.yml` and `docs/ssot/apps/ssot.apps.yml` list `ada-pi` under `tony-dell` host.

## Ada HA PWA (learned 2026-09-13)

### Runtime

- Production URLs: `https://mn01.taila0626a.ts.net/apps/ha/ada-tony/` and `https://mn01.taila0626a.ts.net/apps/ha/ada-michael/` (legacy `/apps/ada_ha_*` 308-redirects)
- Backend:
  - `~/.config/systemd/user/ada-ha-tony.service` running `uvicorn pwa_server:app --port 8002`
  - `~/.config/systemd/user/ada-ha-michael.service` running `uvicorn pwa_server:app --port 8003`
- Env files:
  - `~/.config/secrets/ada-ha-tony.env` → `tony-ha` (`https://tony-dell.taila0626a.ts.net:8123/`), `ADA_INSTANCE_ID=tony`, `ADA_API_KEY` set
  - `~/.config/secrets/ada-ha-michael.env` → `michael-ha` (`http://michael-ha:8123/`), `ADA_INSTANCE_ID=michael`, `ADA_API_KEY` set
  - `ada-pi-pwa.env` on tony-dell also sets `ADA_INSTANCE_ID=tony` (same HA, shared memory) + `ADA_API_KEY`
- `ADA_API_KEY` gates `POST .../entities/{id}/power`, `GET /api/tools`, `POST /api/tools/call`, **and `/ws`** (4401 reject). Read GETs stay open. Optional `ADA_API_KEYS=name:key,...` gives per-caller names in logs + per-key revocation. `POST /api/auth/session` trades a key for a 12h HMAC HttpOnly cookie (`ada_session`, path = app base); `GET /api/auth/status` reports auth state; `POST /api/auth/logout` clears it. PWA: `?api_key=` unlocks (stripped from URL after storing), a Lock/Unlock button in the toolbar manages state, and a full-screen unlock card validates the key before storing.
- Key ops: `scripts/ada-key-url.sh <tony|michael|ada-pi> [--qr]` prints the unlock deep-link; `/apps/ha/pair/` issues named per-device keys + one-time QR links (`POST /api/auth/keys`, persisted to `~/.config/secrets/ada-ha-<inst>-keys.json`, revocable via `DELETE`). `--qr` mints a **one-time** `/redeem/{token}` URL via `POST /api/auth/redeem-token` — burns on first GET, expires in `ADA_REDEEM_TTL_S`=600s, hands the device the key + session cookie); `scripts/rotate-ada-key.sh <instance>` rotates + restarts + prints the new link.
- **`ADA_INSTANCE_ID` is required, fail-fast** (since 2026-09-17, ada-pi `b870d37`): it pins the MDDB memory collections (`ada-ha-snapshots|device-confidence|device-safety|events-<id>`). Never derive collection identity from `HOME_ASSISTANT_URL` — URL changes used to silently orphan all memory (`ada-ha-*-http-127-0-0-1-8123` orphans still exist). Missing/invalid → service refuses to start. Rule: **fail quick and report — no silent fallback for identity config.**
- Caddy: `~/.config/caddy/Caddyfile.mn01` routes `/apps/ha/ada-tony/` to `127.0.0.1:8002` and `/apps/ha/ada-michael/` to `127.0.0.1:8003` (legacy `/apps/ada_ha_*` paths 308 to the canonical ones); tony-dell's Caddyfile also proxies the canonical paths to mn01
- WebSocket: `wss://mn01.taila0626a.ts.net/apps/ha/ada-tony/ws` and `wss://mn01.taila0626a.ts.net/apps/ha/ada-michael/ws`
- Home Assistant: `tony-ha` at `https://tony-dell.taila0626a.ts.net:8123/`, `michael-ha` at `http://michael-ha:8123/`
- Navigation: `https://mn01.taila0626a.ts.net/apps/ha/` and `https://mn01.taila0626a.ts.net/apps/`

### Service commands

- `ssh mn01 'systemctl --user {start,stop,status} ada-ha-tony ada-ha-michael'`
- `ssh mn01 'systemctl --user restart caddy-mn01'`
- Deploy code: `scripts/deploy-ada.sh <mn01|tony-dell|all> [--restart]` — ff-only pull on the runtime checkout, restarts only on `.py`/requirements changes (static files serve from disk), fails fast on dirty tree / wrong tracking / divergence. **Runtime checkouts are read-only consumers of `origin/main` — never commit or merge on mn01/tony-dell.**

### REST endpoints

- `GET /api/home-assistant/entities` — list controllable devices
- `GET /api/home-assistant/sensors?search=<term>&limit=<n>` — list sensor entities
- `GET /api/home-assistant/history?entity_id=<id>&hours=<n>` — fetch raw state history for one sensor
- `GET /api/home-assistant/power-summary?hours=<n>` — G3 power summary (current + min/max/mean over N hours)
- `POST /api/home-assistant/entities/{entity_id}/power` — turn light/switch/fan on or off

### Gemini tools

- `get_home_state` — current person state + watched plugs
- `control_entity` — turn a light/switch/fan/input_boolean on or off
- `get_power_summary` — voice summary of G3 solar/grid/load/battery data and recent history
- `get_sensor_history` — detailed recent history for a specific sensor
- `list_sensors` — list available sensor entities with current state and unit
- `search_sensors` — find a sensor by name or keyword
- `get_dashboard_tab` — read the named tab from the michael-ha tony-test dashboard and return its devices/states

### SSOT

- `docs/ssot/apps/ssot.apps.ada_ha.yml` and `docs/ssot/apps/ssot.apps.yml` list `ada-ha`, `ada-ha-tony`, and `ada-ha-michael` under the `mn01` host.

### Network notes

- `tony-dell.local` (mDNS) is not resolvable from the dev machine; use `tony-dell` (Tailscale) or the Tailscale IP instead.

# ESP32 Test (esp32test) — learned 2026-09-14

## Config

- Source: `esp32/config.yaml`
- Build path: `esp32/.esphome/build/esp32test/`
- ESPHome: installed via `pipx` as `2026.8.2` (Python 3.14.4)
- Board: `esp32dev`, framework `arduino`, chip ESP32-D0WD-V3 rev 3.1, MAC `c0:cd:d6:85:a8:38`

## WiFi

- Active SSID: `Xiaomi_A654`
- IP: `192.168.31.231`, gateway `192.168.31.1`
- Configured networks: `Xiaomi_A654` and `AisMN_2.4G` (both use `starboardwind`)
- 5 GHz entries (`tony5`, `albatros5`, `aismn5g`) removed to fix 2.4 GHz-only ESP32 connection
- `esp32/secrets.yaml` holds `!secret` placeholders for legacy networks and the real MQTT credentials

## MQTT

- Broker: `michael-ha` Mosquitto at `192.168.1.160:1883`
- Credentials: username `mqtt` (password saved to `esp32/secrets.yaml`, `chmod 600`)
- Credentials were found in `michael-ha` `/config/.storage/core.config_entries`
- `michael-ha` HA auto-discovers the device via MQTT; entity IDs:
  - `binary_sensor.esp32_test_node_status`
  - `light.esp32_test_display_backlight`
  - `sensor.esp32_test_connected_ssid`
  - `sensor.esp32_test_ip_address`
  - `sensor.esp32_test_uptime`
  - `sensor.esp32_test_wifi_signal`
  - `sensor.esp32_test_free_heap`

## Flash / access

- USB port: CH340 at `/dev/ttyUSB0` (root:dialout), needs `sudo chmod 666 /dev/ttyUSB0` or `dialout` group
- Compile: `cd chaba && esphome compile esp32/config.yaml`
- USB flash: `esphome run esp32/config.yaml --device /dev/ttyUSB0`
- OTA: `esphome run esp32/config.yaml --device 192.168.31.231`
- Direct `esphome` / ping access requires being on `Xiaomi_A654`; `michael-ha` can see it only through MQTT, not by IP

## Caddy HA subpath redirects (2026-09-15)

- The Caddy subpath URLs under `/apps/ha/<instance>/` are now 308 redirects to the dedicated HTTPS endpoints.
- `tony-ha`: `https://tony-dell.taila0626a.ts.net/apps/ha/tony-ha/` -> `https://tony-dell.taila0626a.ts.net:8123/`
- `michael-dev`: `https://tony-dell.taila0626a.ts.net/apps/ha/michael-dev/` -> `https://tony-dell.taila0626a.ts.net:8124/`
- `michael-ha`: `https://tony-dell.taila0626a.ts.net/apps/ha/michael-ha/` -> `https://nupo4ndqdqydt78zmpq0z5wzp1bdrqgs.ui.nabu.casa/`
- Caddyfile: `~/.config/caddy/Caddyfile.tony-dell`; apply with `caddy fmt --overwrite /home/tony/.config/caddy/Caddyfile.tony-dell` and `systemctl --user restart caddy-tony-dell`.
- HA is bound to loopback (`127.0.0.1:8123` and `127.0.0.1:8124`) and exposed via Tailscale Serve on the same ports.

## Tailscale subnet-route conflict (learned 2026-09-16)

- `tony-dell` advertises `192.168.2.0/24` as a Tailscale subnet route (for remote tailnet access); `michael-ha` advertises `192.168.31.0/24`.
- On nodes physically on `192.168.2.x`, Tailscale table-52 rules prefer the tunnel for the local subnet — LAN peers then see replies from the wrong source IP and TCP breaks (e.g., Deskreen on tony-omen unreachable from the iPad).
- Fix on tony-omen: `lan-route-pref.service` (systemd) adds `ip rule ... to 192.168.2.0/24 priority 5000 lookup main` so LAN traffic uses `wlo1` directly. Check with `ip rule | grep 5000` and `ip route get <lan-ip>`.
- `tony-dell` and `mn01` are on the same LAN and may need the same rule — unverified; check `ip route get` on each before assuming LAN reachability works there.

## NotebookLM (learned 2026-09-15)

- `notebooklm-mcp-cli` (MCP/CLI) stores auth in `~/.notebooklm-mcp-cli/`, managed by `nlm`.
- `notebooklm-py` (REST) uses `storage_state.json`; it expires more quickly than the `nlm` cookies.
- Auth refresh: `~/.local/bin/notebooklm-rest-auth-refresh` runs daily on tony-omen, `rsync`s `storage_state.json` to tony-dell, and restarts `notebooklm-rest`.
- CLI helpers: `~/.local/bin/nlm` (ssh wrapper → `podman exec notebooklm-mcp nlm` on `$NLM_HOST`, default **mn01** — NOT the real binary), `~/.local/bin/nbapi` (REST helper).
- **Re-auth when tokens go stale** (learned 2026-09-18): run `scripts/nlm-reauth.sh` on tony-omen. It invokes the real binary `~/.local/share/nlm-venv/bin/nlm login` (opens Chrome on the local display for Google sign-in), scp's `~/.notebooklm-mcp-cli/profiles/default/{cookies,metadata}.json` to `tony-dell:~/.local/share/notebooklm/.notebooklm-mcp-cli/profiles/default/`, and verifies with `nlm login --check` in the container. `SKIP_BROWSER=1` syncs existing creds without a login window. The `nlm` wrapper cannot do this — it SSHes to a container with no browser ("No supported browser found"), and CDP/openclaw auth only works if the target Chrome already has a Google session.
- REST public URL: `https://tony-dell.taila0626a.ts.net/apps/notebooklm/api/v1/...` with `X-API-Key` from `~/.config/secrets/notebooklm-rest-api.env`.
- Common commands:
  - `nlm notebook list`
  - `nbapi /v1/notebooks`
  - `systemctl --user {start,stop,status} notebooklm-rest`
  - `systemctl --user {start,status} notebooklm-rest-auth-refresh.service`
- Google Drive collections:
  - Top-level folder: `notebooklm/` (`1beIctIVvLYKwsLwRNap7UXi3ZbFnS0xG`)
  - Default collection: `chaba/` (`1H7FHxy5nDxMOmcFtL79lmy_bttV35kjB`)
  - Add by Drive source: `nlm source add <nb> --drive <FILE_ID> --type doc --wait`
  - Add from rclone path: `rclone copy <local> gdrive:notebooklm/chaba` then add the Drive file by ID
- Per-notebook file storage:
  - Drive folder: `gdrive:notebooklm/chaba/notebooks/<notebook-id>/files`
  - Local manifest: `~/.local/share/notebooklm/notebooks/<notebook-id>/manifest.yml`
  - Helper: `nlm-add <notebook-id> <local-file> [-t "<title>"]`
  - `nlm-add` converts `.md`/`.yml`/`.txt` to `.docx` on upload, adds by Drive ID, and records the source in the manifest
- **Source deletion is broken at the API level** (`nlm source delete` / MCP `source_delete` → "Failed to delete source", matches earlier 401s). `notebook_delete` works. Delete individual sources via the NotebookLM web UI if needed.

## Chrome Remote Desktop (tony-dell)

### Service

- Instance unit: `chrome-remote-desktop@tony.service` (system unit, not user unit).
- Status / start / stop:
  - `chrome-remote-desktop --get-status`
  - `sudo systemctl {start,stop,restart} chrome-remote-desktop@tony`
- `chrome-remote-desktop-environment.service` (user) only injects environment; do not rely on it to run the host.

### Known failure modes & fixes

- Default Xorg+dummy path fails as non-root with `parse_vt_settings: Cannot open /dev/tty0 (Permission denied)`. Fix: force Xvfb.
  - Drop-in: `/etc/systemd/system/chrome-remote-desktop@tony.service.d/xvfb.conf`
    ```
    [Service]
    Environment=CHROME_REMOTE_DESKTOP_USE_XVFB=1
    ```
  - Then `sudo systemctl daemon-reload && sudo systemctl restart chrome-remote-desktop@tony`.
- `~/.chrome-remote-desktop-session` must `exec` a long-running desktop/WM process. `startlxqt` (`lxqt-session`) segfaults in the headless Xvfb display; use `startxfce4` instead.
  - Current session file: `exec /usr/bin/startxfce4`

## Chrome Remote Desktop (tony-omen)

- Host config: `~/.config/chrome-remote-desktop/host#ad85c6685ce3fd99d30087e5d5840718.json` (`host_name=tony-omen-remote`, owner tonezzzz@gmail.com, pre-registered — no re-link needed unless the OAuth refresh token dies).
- Start: `env -i HOME=$HOME PATH=/usr/local/bin:/usr/bin:/bin USER=$USER LOGNAME=$USER /opt/google/chrome-remote-desktop/chrome-remote-desktop --start` — start it with a CLEAN env, or leaked `SESSION_MANAGER`/`DBUS_SESSION_BUS_ADDRESS` make the spawned desktop session attach to the real session and exit instantly ("Failure count for 'session'" climbing in `journalctl --user`).
- **Different display model than tony-dell**: here CRD supplies its own virtual X display, so `~/.chrome-remote-desktop-session` must NOT run `startxfce4` (it execs `xinit` → `Xorg.wrap: Only console users are allowed to run the X server`). Correct file (works 2026-09-17):
  ```bash
  #!/bin/bash
  unset SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS XAUTHORITY GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
  exec /usr/bin/dbus-run-session -- /usr/bin/xfce4-session
  ```
- Requires `dbus-x11` (installed 2026-09-17); without it xfce4-session dies with "dbus-launch not found" after ~5s.
- Deleting the session file restores the interactive session chooser (`xsession_chooser`).
- This is a separate virtual session, NOT a mirror of the physical `:0` monitor — for screen mirroring use Sunshine/Moonlight. (Deskreen was removed 2026-09-19.) Runbook: `docs/kb/media-casting-runbook.md`.

## Web app deployment (tony-dell Caddy)

### Source vs served directory

- Repo source: `stacks/web/public/apps/`
- Caddy `file_server` root: `~/.config/caddy/public/apps/` on tony-dell
- Caddy `handle_path /apps/*` in `~/.config/caddy/Caddyfile.tony-dell` serves from the root above, not the repo
- Changing files in the repo does **not** make them live until they are copied to Caddy's public directory

### Workflow

1. Add app files to `stacks/web/public/apps/<your-app>/` (with an `index.html`)
2. Regenerate `apps.yml`:
   - `python3 /home/tony/CascadeProjects/chaba/scripts/apps-yml-generate.py --generate --verify`
3. Commit/push
4. The `apps-health-sync.timer` will:
   - regenerate `docs/ssot/infrastructure/ssot.health.home.apps.yml`
   - `rsync` public apps to tony-dell's Caddy root
   - run a live HTTP verification against `https://tony-dell.taila0626a.ts.net`

### Manual sync

```bash
rsync -avz /home/tony/CascadeProjects/chaba/stacks/web/public/apps/ tony-dell:/home/tony/.config/caddy/public/apps/
```

### Verification

- Local consistency: `python3 scripts/apps-yml-generate.py --verify`
- Live HTTP checks: `python3 scripts/apps-yml-generate.py --verify --live`
- Timer: `systemctl --user status apps-health-sync.timer` (daily)
- When working, the CRD virtual display lives on `:20` (`/tmp/.X11-unix/X20`).

## NotebookLM as the Chaba KB

### Notebook

- ID: `fdfd3483-6b7e-4cb0-85f3-7f060698769c`
- Title: `Chaba KB search benchmark`
- URL: `https://notebooklm.google.com/notebook/fdfd3483-6b7e-4cb0-85f3-7f060698769c`

### What is synced

- `AGENTS.md`
- `README.md`
- `docs/ssot/infrastructure/*.yml`
- `docs/ssot/apps/*.yml`
- `docs/ssot/ssot*.yml`
- `docs/kb/**/*.md` and `*.yml`
- `apps/dev/v0/README.md`
- `experiments/gold-thb-usd-causality/app/README.md`
- `experiments/meshtastic-th-collector/README.md`
- `mcp-servers/mcp-health/README.md`
- `stacks/ha-live/README.md`
- `workflows/README.md`

### Sync

- Script: `scripts/notebooklm-kb-sync.py`
- Timer: `systemctl --user status notebooklm-kb-sync.timer` (daily)
- Manual: `python3 scripts/notebooklm-kb-sync.py`
- Config: `docs/ssot/infrastructure/ssot.values.yml` → `notebooklm.sync`
- Dry run: `python3 scripts/notebooklm-kb-sync.py --dry-run`
- Post-commit hook: `.git/hooks/post-commit` runs an incremental sync when `docs/kb/`, `docs/ssot/`, `AGENTS.md`, or `README.md` change

### How to query

```bash
# General query across all sources
nlm query notebook fdfd3483-6b7e-4cb0-85f3-7f060698769c "<your question>" --timeout 120

# Scoped to a category or a single chunk
nlm query notebook fdfd3483-6b7e-4cb0-85f3-7f060698769c "<your question>" \
  --source-ids <source-id-1>,<source-id-2> --timeout 120

# Cached query wrapper (stores answers for 24h)
nlmq fdfd3483-6b7e-4cb0-85f3-7f060698769c "What is MDDB used for?"

# Cite a source back to original repo files
nlm-cite kb/mddb
nlm-cite 40893dfc-243a-4988-bd77-f1bc916ee303

# Helper: query by source title pattern (uses the sync manifest)
python3 scripts/notebooklm-query.py "kb/mddb" "What is MDDB used for?"
python3 scripts/notebooklm-query.py "ssot/infrastructure" "What is the tony-dell Tailscale IP?"
python3 scripts/notebooklm-query.py "-" "Summarize the Home Assistant setup."
```

### Helper scripts

- `nlmq` — cached `nlm query` wrapper (`~/.local/bin/nlmq`)
  - Same interface as `nlm query notebook <id> <question>`.
  - Stores the raw answer in `~/.local/share/notebooklm/query-cache/` for 24h.
  - Set `NLMQ_TTL` to change the cache lifetime in seconds.
- `nlm-cite` — map a NotebookLM source title or source_id back to repo files
  - `nlm-cite kb/mddb`
  - `nlm-cite 40893dfc-243a-4988-bd77-f1bc916ee303`
  - Uses `data/notebooklm-kb-sync-manifest.yml`.
- `chaba-ask` — pick the right consumer for a natural-language question
  - `chaba-ask "How do I restart the NotebookLM auth refresh?"` → routes to `nlmq`
  - `chaba-ask "What is the tony-dell Tailscale IP?"` → tells you to use `mcp_query_ssot`
- `nlm-pr-draft` — draft a PR description from the current branch's diff
  - `nlm-pr-draft` or `nlm-pr-draft --base master`
- `nlm-explain-log` — ask the KB to explain a recent log file
  - `nlm-explain-log` or `nlm-explain-log -l /path/to.log`
- `nlm-status` — list active sources in the Chaba KB notebook
  - `nlm-status`
- `make` shortcuts — see `Makefile`:
  - `make ssot`, `make kb`, `make kb-dry`, `make nlmq Q="..."`, `make nlm-cite SOURCE=kb/mddb`
- `verify-agents` — check that `AGENTS.md` bash snippets resolve to real executables/scripts
  - `python3 scripts/verify-agents-commands.py`

### Notes

- Sync is incremental: only chunks whose sha256 changed are re-uploaded.
- `--force` will delete and re-add all sources for a full refresh.
- Sources are archived in Drive via `nlm-add`.

## MDDB / chaba-glossary

- Sync: `python3 scripts/sync-ssot-to-mddb.py` creates `chaba-glossary` from `ssot.values.yml` and `infrastructure-ssot` from all SSOT YAML.
- Timer: `systemctl --user status ssot-mddb-sync.timer` (daily)
- Exact values: query `chaba-glossary` (uses plain-English value statements).
- Topic search: query `infrastructure-ssot` (raw SSOT YAML).
- Example:
  ```bash
  curl -sS -X POST http://127.0.0.1:11023/v1/search \
    -H "Content-Type: application/json" \
    -d '{"collection":"chaba-glossary","query":"Tailscale IP of tony-dell","limit":1}'
  ```
- See `docs/kb/experiments/notebooklm-kb-search-benchmark-2026-09-15.md` for the comparison with MDDB.

## Quick HA device assessment

- Script: `scripts/home-assistant/assess-device.py`
- One-liner:
  ```bash
  python3 /home/tony/CascadeProjects/chaba/scripts/home-assistant/assess-device.py michael-ha/sr258
  python3 /home/tony/CascadeProjects/chaba/scripts/home-assistant/assess-device.py michael-ha/sensor.foo
  python3 /home/tony/CascadeProjects/chaba/scripts/home-assistant/assess-device.py --format json --verbose michael-ha/number.sr258_temperature
  ```
- Supported instances: `michael-ha`, `michael-dev`, `tony-ha`
- Tokens are read from `~/.config/secrets/ha-michael-live.env`, `~/.config/secrets/ha-michael-dev.env`, `~/.config/secrets/home-assistant-token.env` (or the matching `*_TOKEN` env vars).
- Use the `home-assistant` MCP server for deeper config or write operations; `assess-device.py` is the fast read-only fallback.

# AI Hub extension + Chrome remote debugging (learned 2026-09-17)

## AI Hub extension

- Source: `stacks/web/public/apps/ai-hub-extension/` (loaded unpacked, Chrome MV3).
- Targets: chatgpt, gemini, gemini-images, claude, midjourney, aistudio. Prompt send/debug uses inline `chrome.scripting.executeScript` — no content-script dependency.
- Cookie bridge: `cookie-bridge.mjs` runs on tony-omen `127.0.0.1:9876` (systemd user `cookie-bridge.service`, env `~/.config/ai-hub/cookie-bridge.env`). POST `/cookies` writes `~/.notebooklm/profiles/default/storage_state.json`, rsyncs to `tony-dell:~/.local/share/notebooklm/notebooklm-rest-data/storage_state.json` (the path the container mounts — NOT `notebooklm/`), restarts `notebooklm-rest`. Also `GET /health`, `POST /debug-screenshot`, `POST /page-dump`. Also reachable via Caddy: `https://tony-dell.taila0626a.ts.net/apps/notebooklm-cookies`. Bridge refuses unchanged sets and any sync that would drop auth/DBSC-bound cookies (SID/HSID/APISID).
- **DBSC**: Chrome ≥136 binds `SID`/`HSID`/`APISID` to the device — `chrome.cookies` never sees them, so extension-captured state is always incomplete. The working path is `master_token.json` (minted cookies, no export): bootstrap via `~/.local/share/nlm-venv/bin/notebooklm login --master-token --account tonezzzz@gmail.com --cdp-url http://127.0.0.1:9228` (gpsoauth is in `nlm-venv`). The EmbeddedSetup sign-in tab appears to HANG after "I agree" — cosmetic only; the oauth_token is captured on the redirect and `master_token.json` + full `storage_state.json` (with SID) are written anyway. After bootstrap, `notebooklm auth refresh` re-mints headlessly.
- `nbapi` wrapper (tony-dell `~/.local/bin/nbapi`) reads `NOTEBOOKLM_REST_API_KEYS` (first entry) from `~/.config/secrets/notebooklm-rest-api.env`. Master key rotated 2026-09-17; scoped keys `ada-michael`/`ada-tony` in `NOTEBOOKLM_REST_KEY_SCOPES` unchanged.
- Extension storage keys: `bridgeUrl`, `cookiesJson`, `lastCookieSync`, `selectedTargets`, `nb*` fields. A stale saved `bridgeUrl` silently overrides the HTML default — this was the "capture/send no response" cause in the old profile.
- Auto-sync fires on ANY google-domain `cookies.onChanged` with 60s cooldown; every sync restarts `notebooklm-rest` on tony-dell. Verified working (syncs ~every minute while Google tabs are open) — restart churn may be worth raising.

## Chrome remote debugging (Chrome ≥136)

- Chrome 136+ **refuses** `--remote-debugging-port` on the default user-data-dir ("DevTools remote debugging requires a non-default data directory").
- Working setup on tony-omen: cloned profile at `~/.config/google-chrome-debug` — `rsync -a` of `Default/` minus `File System`, `Service Worker`, `Cache`, `Code Cache`, `GPUCache`, `Crashpad`, `blob_storage`, plus `Local State`. Google login carries over on the same machine (cookies decrypt via same OS keyring).
- Launch: `DISPLAY=:0 google-chrome --remote-debugging-port=9228 --user-data-dir=$HOME/.config/google-chrome-debug --no-first-run --no-default-browser-check`
- Verify: `curl http://127.0.0.1:9228/json/version`. playlive's `tony-omen` host already expects CDP on 9228.
- This box IS tony-omen — run chrome/debug commands locally, not over ssh. `pkill -f remote-debugging` will match and kill the calling shell; use `pgrep -f "^/opt/google/chrome"` (anchored to the real binary path).

## chrome-devtools-mcp

- Config: `.devin/mcp_config.local.json` (gitignored) — `npx -y chrome-devtools-mcp@1.9.0 --browserUrl http://127.0.0.1:9228 --no-usage-statistics --no-performance-crux`. New sessions pick it up on restart.
- 29 tools; page-scoped tools require `pageId` (pageIdRouting on by default — get IDs from `list_pages`).
- **Known bug**: frozen/discarded background tabs make `browser.pages()`-based tools (`list_pages`, `take_snapshot`, `new_page`… ) hang forever — upstream issues #1230/#1918/#2114, unfixed. Workaround: don't restore big sessions in the debug profile (we deleted `Default/Sessions` + `Current/Last Session|Tabs`), or activate tabs first.
- Manual stdio test: pipe JSON-RPC `initialize` + `tools/call` lines to the npx command; **keep stdin open** (`sleep` after printf) — closing stdin kills the server mid-call.

## Inspecting the extension via CDP

- AI Hub unpacked id: `emeljcclmededmnnnoejcccnbeadeilm` (sha256 of path → a-p map).
- Its MV3 service worker only wakes on `action.onClicked` + `cookies.onChanged` (`serviceworkerevents` in `Default/Preferences`); `tabs.onActivated` listeners added later aren't wake-events until the SW re-registers (reload/bump manifest version). To wake it over CDP: set a cookie on any page (`document.cookie="x=1"` or `Network.setCookie`), then connect to its `webSocketDebuggerUrl` and `Runtime.evaluate` `chrome.*` APIs (`awaitPromise:true`).
- In the debug profile: 85 google cookies, 14 notebooklm cookies — login carried over.

## Samsung TV / TV-corner power flow (learned 2026-09-18)

`switch.plug_tv` on tony-ha powers the WHOLE TV corner: Samsung panel + TrueID box + Tenda repeater. When `media_player.tv_40c5000` (or the TrueID `media_player.tony_tv`) is `unavailable`, follow this flow instead of just reporting it dead:

1. Check `switch.plug_tv` state. If `off`, ASK the user whether to turn it on (HA `switch.turn_on`) — don't just say the TV is off.
2. If plug is `on` but TV still unavailable: the panel is in standby (NIC dies, nothing pings). Ask the user to power it on with the remote/button — a 2010 Samsung does NOT auto-boot on AC restore.
3. Wait ~60s after power-on for DLNA/UPnP to come up (ports 52235/52396/5601), then re-check and continue the task.
4. The repeater and TrueID box share the plug — they take their own boot time after plug-on (repeater: Tenda UI at .72/.73/.82 after ~1min; TrueID: Chromecast on 8008/8009).

## On-demand casting (built 2026-09-19)

tony-ha cast lifecycle — every cast goes through the gate, nothing targets dead devices:

- `script.cast_power_on(target)` — `tv` = Samsung DLNA (`media_player.tv_40c5000`), `box` = TrueID Chromecast (`media_player.tony_tv_cast`). If target unavailable → `switch.plug_tv` on, sets `input_boolean.cast_powered_by_us`, waits 90s for the entity, notifies on timeout. Always (re)starts `timer.cast_idle` (5 min).
- `input_boolean.youtube_search_pending` gates `automation.cast_youtube_from_search_result`: `youtube_search_on_query` arms it on a new `input_text.youtube_query`, and the search-result automation requires it `on` + query `last_changed` < 30 min, then clears it. Added 2026-09-20 because `sensor.youtube_search_result` polls every 10 min and YouTube's top result kept alternating, re-firing `cast_power_on` → `plug_tv` on in a loop. Passive poll flips now do nothing; only a fresh query casts.
- `script.cast_cleanup` — `shell_command.cast_host_cleanup` (ssh tony-omen, kills deskreen-ce + cast ffmpeg feeders), turns off both cast targets, cancels timer, clears flag. TV stays powered; only cast-side state unwinds. shell_command defined in tony-ha configuration.yaml (ssh -i /config/.ssh/id_tony_omen tony@tony-omen.taila0626a.ts.net — container DNS maps 'tony-omen' to a stale 192.168.1.x, use the FQDN).
- `script.cast_camera` — power_on(box) → camera.xiaomi_c201 → verify playing → fallback `camera.xiaomi_c201_sd` → notify on failure. LAN-only; no cloud path exists for Xiaomi→Chromecast (Google cloud casting is Nest-only).
- `automation.cast_idle_shutdown` — timer.finished + flag on → if either target `playing`: skip + persistent-notification + restart timer; else `cast_cleanup`.
- `automation.cast_activity_reset` — either target → `playing` + flag on → restart timer.
- Wrapped with the gate (first action = `script.cast_power_on` box): `1788623518229` (Thai hello TTS), `assist_tv_control`, `cast_youtube_on_input`, `youtube_search_on_query`, `cast_youtube_from_search`, `cast_youtube_from_picker`, `youtube_request_handler`, `youtube_auto_play_next`, `youtube_queue_control` — in `/home/tony/.config/home-assistant/automations.yaml` on tony-dell (backup `automations.yaml.bak-20260918`).
- The 11 `assist_cast_*`/`cast_from_youtube_result_button`/`update_youtube_result_buttons` entities were orphaned registry entries — deleted 2026-09-20 via ha_remove_entity.
- Cast target entity is `media_player.tony_tv_cast` (Google Cast), NOT `media_player.tony_tv` (Android TV Remote) — don't confuse them.

## Chaba admin Events feed (built 2026-09-20)

`chaba-admin` dashboard on tony-ha gained an **Events** tab (`/chaba-admin/events`) — a unified, filterable event feed plus the native HA logbook.

- Feed file: `/config/www/chaba-events.json` on tony-dell (served at `/local/chaba-events.json`). Writer: `/config/scripts/chaba-event-log.py` (repo: `stacks/tony-dell/tony-ha/scripts/`) — flock + atomic write, prunes >24h, caps 300, `add`/`ack`/`list`. Runs on host python3 or in-container `/usr/local/bin/python3` — same script both places.
- Producers call `shell_command.chaba_event` (payload = base64 JSON: `{title, category, severity, body, link, requires_response, confidence}`) from HA, or `python3 .../chaba-event-log.py add '<json>'` over SSH from anywhere. `shell_command.chaba_event_ack` marks `responded`. Wired today: all four `ada_pair_*` scripts (scripts.yaml) and `deploy-ada.sh` (emit per-host, requires_response on failure).
- Card: `custom:chaba-events-card` (`/local/chaba-events-card.js`, repo `stacks/tony-dell/tony-ha/www/`) — merges the JSON feed with live `persistent_notification` entities (always requires-response, Dismiss calls `persistent_notification.dismiss`). Unresolved response-needed events pin to top with a pulsing border (reduced-motion safe); `confidence < 0.6` gets an outlined chip.
- Shared visibility state (same on every device): `input_text.chaba_events_filter` holds `{"hidden": ["category", ...]}` — new categories self-register, no YAML change needed. `input_boolean.chaba_events_show_logbook` gates the conditional native `logbook` card (24h). Gotcha: HA 2026.8 logbook cards error with "target has no entities" unless `entities:`/`target:` is set — it carries a curated list of admin-relevant entities.
- To add a new producer from a HA automation/script: `action: shell_command.chaba_event` with `payload: "{{ {...} | to_json | base64_encode }}"`. From a shell script: `ssh tony-dell python3 /home/tony/.config/home-assistant/scripts/chaba-event-log.py add '<json>'`.
