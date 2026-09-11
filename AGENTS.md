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

- tony-ha: `http://tony-dell:8123`
- michael-dev: `http://127.0.0.1:8124` / `https://tony-dell.taila0626a.ts.net:8124`
- michael-ha: `http://michael-ha:8123` / `https://nupo4ndqdqydt78zmpq0z5wzp1bdrqgs.ui.nabu.casa/`
- tony-test views: `https://tony-dell.taila0626a.ts.net:8124/tony-test/{pf3,pf4,pfg,pfg1,pfg2,tpl,data}`

## Token files

- michael-dev: `~/.config/secrets/ha-michael-dev.env` (`HASS_TOKEN`)
- michael-ha: `~/.local/share/home-assistant-michael/ha-token` (raw token file, NOT `ha-michael-live.env`)
- Never paste tokens into chat or commit them.
- The `michael-dev` token in `~/.config/secrets/ha-michael-dev.env` is valid and works for REST (verified 2026-09-04).
- Tailscale SSH (`ssh tony-dell`) periodically requires a browser auth check; it prints a `login.tailscale.com/a/...` link — ask the user to open it, then retry.

## Build / deploy commands

- Build card: `cd /home/tony/CascadeProjects/sunsynk-power-flow-card && npm run build`
- Restart michael-dev: `ssh tony-dell 'systemctl --user restart michael-dev.service'`
- Restart michael-ha: `ssh michael-ha 'ha core restart'`
- Deploy card bundle: `./scripts/home-assistant/deploy-card.sh [--host michael-dev|michael-ha|all]` — builds, derives next version from the *target's* remote `lovelace_resources`, scp's, restarts, verifies HTTP 200. Version numbers are per-host; verify parity by `md5sum`, not version.
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

## Current state (2026-09-07)

- Active card bundle: `v100` on michael-dev / `v99` on michael-ha — same md5 (`fe9942680fb5…`), source commit `f7aa98d`. Version numbers are per-host; compare content by md5.
- Deployed: `michael-dev` (PF3/PF4/PFG/PFG1/PFG2/TPL/Dossier) and `michael-ha` (PFG2 first tab, TPL after SK).
- `cardstyle` branches: `lite` (PF3/PF4), `pfg` (PFG/PFG1/TPL), `pfg2` (PFG2 — same renderer as `pfg`, `pfg_grid_size` default 15; `pfg2-card.ts` was removed in v71).
- `pfg`/`pfg2` full key set — `pfg_images`, `pfg_labels`, `pfg_label_pos`, `pfg_icons`, `pfg_values`, `pfg_value_labels`, `pfg_value_label_pos`, `pfg_image_zoom`, `pfg_image_fit`, `pfg_lines`, `pfg_spans` (incl. `RxC` and responsive `{square,portrait,landscape}`), `pfg_radius`, `pfg_border`, `pfg_sums`, `pfg_grid_size`, `pfg_grid_cols`, `pfg_grid_rows`, `pfg_grid_width`, `pfg_hide_grid`, `pfg_transparent`, `pfg_fit_screen`, `pfg_inverter_at`, `pfg_charts` (gauge/bar/history/cycle/bars) — see `ssot.home-assistant.design.yml`.
- PFG2 layout (9 cols × 10 rows, transparent, hide-grid, free-fit): PV1 `1,1`, PV2 `1,4`, Grid `1,7`, PV Total `3,1`, Inverter `3,4`, Batt `5,1`, Home `5,7`, Living `7,4`, Kitchen `7,7`, Laundry `9,4`, Pool `9,7` — all spans `2x3`. Empty band `r3–4, cols 7–9` is intentionally open.
- TPL tab holds single-tile templates applied via `apply-tpl.py` (e.g. `PV.b1`, `Temp`, `Freq`, `Daily`).
- The `michael-dev` token in `~/.config/secrets/ha-michael-dev.env` is valid and works for REST and websocket.
- Dashboard snapshot is `docs/home-assistant/dashboards/tony-test-current.json`.
- Post-restart MCP verification: all 18 configured Devin MCP servers are reachable after tony-dell restart. `michael-dev` and `tony-ha` `ha_mcp_tools` require `_READY_STALL_TIMEOUT_SECONDS=300s` / `_READY_TOTAL_CAP_SECONDS=900s` in `embedded_server.py` to avoid startup timeout on HA 2026.9.0. `github` MCP now uses `~/.config/devin/mcp-scripts/mcp-github-proxy.py`.

## XMEye VMS on tony-dell

- Container: `xmeye-vms-vnc` (Podman), exposes VNC on `192.168.2.67:5900` (no password).
- Browser noVNC: `http://tony-dell/apps/vnc/` -> `http://tony-dell/apps/vnc/vnc.html` (noVNC) -> `ws://tony-dell:6081/` (websockify proxy to VNC; port 6080 is reserved for `websockify-macbook.service`).
- Websockify: `websockify 0.0.0.0:6081 127.0.0.1:5900` on tony-dell.
- Wine virtual desktop startup (fixes wireframe/repaint issue): `wine explorer /desktop=VMS,1280x720 VMS.exe` from `/app` inside the container.
- VMS config: `/home/tony/.cache/xmeye-vms/vms-runtime/config.ini`.
- VMS app login: `admin` / `admin` (saved hash `F360C0DD174588FA` in `config.ini` `[Login]` `password`).
- Device/DVR test password supplied by user: `amc123456`.
- Second DVR Cloud/Serial ID to add: `d811d82e21d6c031`.
- QR files for import: `Z:\\app\\qr\\S__7610372.jpg` and `Z:\\app\\qr\\QR.jpg` inside the VMS (mounted from `/home/tony/.cache/xmeye-vms/vms-runtime/qr/`).
- Set `autologin=true` in `config.ini` after the saved hash is in place to skip the login prompt on next restart.
