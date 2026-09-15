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

- tony-ha: `https://tony-dell.taila0626a.ts.net:8123`
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

# Devin on tony-dell — crash/runbook (2026-09-12)

## Restart after a crash

`devin-desktop` must be launched with the active X display on tony-dell. The process is *not* a systemd service; it is started as a background `nohup` job and shows up in `pgrep -a -f devin-desktop`.

Quick restart command:

```bash
ssh tony-dell 'export DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority; nohup /usr/bin/devin-desktop > /home/tony/.local/share/devin/cli/devin-restart-20260912.log 2>&1 </dev/null &'
```

Verify:

```bash
ssh tony-dell 'pgrep -a -f devin-desktop | grep -v "pgrep\|ssh\|tailscaled"'
```

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

- Development URL: `https://tony-dell.taila0626a.ts.net/apps/ada_ha/`
- Backend: `~/.config/systemd/user/ada-ha-pwa.service` running `uvicorn pwa_server:app --port 8002`
- Env files:
  - `~/.config/secrets/ada-ha-tony.env` → `tony-ha` (`http://127.0.0.1:8123`)
  - `~/.config/secrets/ada-ha-michael.env` → `michael-ha` (`http://michael-ha:8123`)
- Caddy: `~/.config/caddy/Caddyfile.tony-dell` routes `/apps/ada_ha_tony/` to `127.0.0.1:8002` and `/apps/ada_ha_michael/` to `127.0.0.1:8003`
- WebSocket: `wss://tony-dell.taila0626a.ts.net/apps/ada_ha_tony/ws` and `wss://tony-dell.taila0626a.ts.net/apps/ada_ha_michael/ws`
- Home Assistant: `tony-ha` at `http://127.0.0.1:8123`, `michael-ha` at `http://michael-ha:8123`
- Navigation: `https://tony-dell.taila0626a.ts.net/apps/ha/` and `https://tony-dell.taila0626a.ts.net/apps/`

### Service commands

- `ssh tony-dell 'systemctl --user {start,stop,status} ada-ha-pwa'`
- `ssh tony-dell 'systemctl --user restart caddy-tony-dell'`

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

- `docs/ssot/apps/ssot.apps.ada_ha.yml` and `docs/ssot/apps/ssot.apps.yml` list `ada-ha` under `tony-dell` host.

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

## NotebookLM (learned 2026-09-15)

- `notebooklm-mcp-cli` (MCP/CLI) stores auth in `~/.notebooklm-mcp-cli/`, managed by `nlm`.
- `notebooklm-py` (REST) uses `storage_state.json`; it expires more quickly than the `nlm` cookies.
- Auth refresh: `~/.local/bin/notebooklm-rest-auth-refresh` runs daily on tony-omen, `rsync`s `storage_state.json` to tony-dell, and restarts `notebooklm-rest`.
- CLI helpers: `~/.local/bin/nlm` (MCP/CLI via tony-dell container), `~/.local/bin/nbapi` (REST helper).
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

