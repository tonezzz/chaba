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
- michael-live: `~/.config/secrets/ha-michael-live.env` (`HASS_TOKEN`)
- Never paste tokens into chat or commit them.
- The `michael-dev` token in `~/.config/secrets/ha-michael-dev.env` is valid and works for REST (verified 2026-09-04).

## Build / deploy commands

- Build card: `cd /home/tony/CascadeProjects/sunsynk-power-flow-card && npm run build`
- Restart michael-dev: `ssh tony-dell 'systemctl --user restart michael-dev.service'`
- Push dashboard config live (no restart): `python3 scripts/home-assistant/push-dashboard.py https://tony-dell.taila0626a.ts.net:8124 tony-test --mutate /tmp/mutate.py` (requires `source ~/.config/secrets/ha-michael-dev.env`)
- Sync live dashboard into repo: `./scripts/home-assistant/sync-ssot-from-live.sh`
- Sync SSOT to MDDB: `python3 scripts/sync-ssot-to-mddb.py`
- Validate all SSOT: `node scripts/ssot-validate-all.mjs`

## Common tasks

- Dashboard config changes (card layout, lines, images — anything already supported by the bundle): mutate live via `push-dashboard.py` over websocket, then `sync-ssot-from-live.sh`. No rebuild or restart needed; HA refreshes Lovelace automatically.
- Update the forked card: run `./scripts/home-assistant/deploy-card.sh` — builds, derives the next version from remote `lovelace_resources`, scp's, restarts `michael-dev`, verifies HTTP 200.
- Reorder or add a tab: prefer `push-dashboard.py` websocket mutate; `.storage` edits directly require an HA restart to take effect.
- Fix SVG text overlay: check `Battery*_SOC` `<svg>` display condition in `src/components/compact/bat/bat-elements.ts` so plain text hides when combined `{target}% | {current}%` is visible.
- Verify visually: use a logged-in Chrome profile or browser dev tools on the card shadow root.
- Guard against bundle drift: `sync-ssot-from-live.sh` picks the newest `www/` bundle by version. Remove obsolete `sunsynk-power-flow-card-fork-v*.js` bundles or cross-check `lovelace_resources` before committing.

## Current state (2026-09-05)

- Active card bundle: `v71` (`sunsynk-power-flow-card-fork-v71.js`), source commit `95ddb0c`.
- Deployed to `michael-dev` (PF3/PF4/PFG/PFG1/PFG2/TPL) and `michael-ha` (PF3).
- `cardstyle` branches: `lite` (PF3/PF4), `pfg` (PFG/PFG1/TPL), `pfg2` (PFG2 — same renderer as `pfg`, `pfg_grid_size` default 15; `pfg2-card.ts` was removed in v71).
- `pfg`/`pfg2` support `pfg_images`, `pfg_labels`, `pfg_icons`, `pfg_values`, `pfg_image_zoom`, `pfg_lines`, `pfg_spans`, `pfg_radius`, `pfg_sums`, `pfg_grid_size`, `pfg_grid_width` — see `ssot.home-assistant.design.yml` for anchor syntax and line semantics.
- The `michael-dev` token in `~/.config/secrets/ha-michael-dev.env` is valid and works for REST and websocket.
- Dashboard snapshot is `docs/home-assistant/dashboards/tony-test-current.json`.
