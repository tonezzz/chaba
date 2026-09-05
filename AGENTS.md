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
- PF3 test view: `https://tony-dell.taila0626a.ts.net:8124/tony-test/pf3`
- PFG (cardstyle: pfg) test view: `https://tony-dell.taila0626a.ts.net:8124/tony-test/pfg`

## Token files

- michael-dev: `~/.config/secrets/ha-michael-dev.env` (`HASS_TOKEN`)
- michael-live: `~/.config/secrets/ha-michael-live.env` (`HASS_TOKEN`)
- Never paste tokens into chat or commit them.
- Note: the `michael-dev` token is currently invalid and should be regenerated from the HA profile → Security → Long-Lived Access Tokens if REST/Playlive access is needed.

## Build / deploy commands

- Build card: `cd /home/tony/CascadeProjects/sunsynk-power-flow-card && npm run build`
- Restart michael-dev: `ssh tony-dell 'systemctl --user restart michael-dev.service'`
- Sync live dashboard into repo: `./scripts/home-assistant/sync-ssot-from-live.sh`
- Sync SSOT to MDDB: `python3 scripts/sync-ssot-to-mddb.py`

## Common tasks

- Reorder or add a tab: edit `michael-dev:/config/.storage/lovelace.tony_test`, then snapshot with `sync-ssot-from-live.sh`.
- Update the forked card: build, copy `dist/sunsynk-power-flow-card.js` to `michael-dev:/home/tony/.config/michael-dev/www/sunsynk-power-flow-card-fork-v{N}.js`, update `.storage/lovelace_resources`, restart `michael-dev`.
- Fix SVG text overlay: check `Battery*_SOC` `<svg>` display condition in `src/components/compact/bat/bat-elements.ts` so plain text hides when combined `{target}% | {current}%` is visible.
- Verify visually: use a logged-in Chrome profile or browser dev tools on the PF3/PFG shadow root.
- Guard against bundle drift: `sync-ssot-from-live.sh` picks the newest `www/` bundle by version. Remove obsolete `sunsynk-power-flow-card-fork-v*.js` bundles or cross-check `lovelace_resources` before committing.

## Current state (2026-09-04)

- Active card bundle: `v31` (`sunsynk-power-flow-card-fork-v31.js`), source commit `95ddb0c`.
- Deployed to `michael-dev` (PF4 + PFG) and `michael-ha` (PF3); PF3 visually verified on `michael-ha` via long-lived token.
- `PF4` is the dev mirror of `PF3`; `PFG` is a new `cardstyle: pfg` test view at `/tony-test/pfg` (not `cardstyle: full`).
- Dashboard snapshot is `docs/home-assistant/dashboards/tony-test-current.json`.
- `michael-dev` long-lived token in `~/.config/secrets/ha-michael-dev.env` is still invalid and must be regenerated for Playlive/REST access.
