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

## Current state (2026-09-09)

- Active card bundle: `v199` on BOTH hosts. Per-host counters; verify parity with `deploy-card.sh --check`.
- Chart code is modularized under `src/cards/pfg/` (registry + `chartOverlayStyle` + per-type files in `charts/`). `pfg-shared.ts` is gone — update imports to `./pfg`.
- `deploy-card.sh` gained `--prune` (keeps active + newest backup) and a worktree drift guard (warns on unmerged worktree branches).
- echarts/echarts-gl are vendored at `/local/echarts-5.5.1.min.js` + `/local/echarts-gl-2.1.0.min.js` on both hosts; `surface3d`/`bar3d` try local first, CDN fallback.
- 3D chart lessons (G1 surface3d / G2 bar3d): use `xAxis3D.type: 'category'` + `data` order for hour axes — `inverse` on a `value` axis is ignored by ECharts GL. See `pfg_3d_charts` runbook in `docs/ssot/infrastructure/ssot.home-assistant.howto.yml`.
- History/accumulating charts share the localStorage incremental cache policy (`data_cache_policy` in `ssot.home-assistant.design.yml`).
- michael-ha credentials: API/websocket token = `~/.config/secrets/ha-michael-live.env` (the `ha-token` file was refreshed to the same value 2026-09-08); UI login = `~/.local/share/home-assistant-michael/credentials.json` (`nakva`).
- michael-ha sidebar verified visually: Overview, Dossier, Map, Tony test + built-ins (Energy/Activity/History/File editor/HA-MCP/HACS/Matter Server/Settings/Notifications).
- michael-ha tony-test tabs: `V0 (p0) → V1 (p0-2) → G1 → SK → TPL → juWorkshop → Solar Assistant → glass → Weather`.
- New `/local/` assets may 404 in cached browsers while curl returns 200 — bump the reference `?v=N` in the config (runbook: `stale_local_asset_404` in howto SSOT).
- `apply-tpl.py` gained `--bg` (forces copied charts to `position: "bg"`).
- Dashboard snapshot is `docs/home-assistant/dashboards/tony-test-current.json`.
