# PF3 / Home Assistant Runbook

This runbook covers the PF3 dashboard, the forked `sunsynk-power-flow-card`, and the four-battery layout used in the `tony-test` dashboard on `michael-dev`.

## Quick links

- SSOT instances: `docs/ssot/infrastructure/ssot.home-assistant.instances.yml`
- Dashboard SSOT: `docs/ssot/infrastructure/ssot.home-assistant.dashboards.yml`
- Entity mapping SSOT: `docs/ssot/infrastructure/ssot.home-assistant.entities.yml`
- Card source/design SSOT: `docs/ssot/infrastructure/ssot.home-assistant.cards.yml` and `ssot.home-assistant.design.yml`
- Build/runbook SSOT: `docs/ssot/infrastructure/ssot.home-assistant.howto.yml`
- Live test URL: `https://tony-dell.taila0626a.ts.net:8124/tony-test/pf3`
- Card repo: `/home/tony/CascadeProjects/sunsynk-power-flow-card`
- Build command: `npm run build`
- Build output: `dist/sunsynk-power-flow-card.js`

## Dashboard structure

The `tony-test` dashboard is stored in `.storage` on `michael-dev`, not in the repo YAML snapshot. The repo snapshot is at `docs/home-assistant/dashboards/tony-test-current.json` and is updated by `scripts/home-assistant/sync-ssot-from-live.sh`.

New test views have been added:

- `PF4` (`cardstyle: lite`, `/tony-test/pf4`) is a copy of PF3 used for dev verification.
- `PFG1` (`cardstyle: pfg`, `/tony-test/pfg1`) is an experimental pfg grid layout.
- `PFG` (`cardstyle: pfg`, `/tony-test/pfg`) is the original pfg test view, **not** `cardstyle: full`.
- `PFG2` (`cardstyle: pfg2`, `/tony-test/pfg2`) renders a 15x15 grid (default `pfg_grid_size` 15).
- `TPL` (`cardstyle: pfg`, `/tony-test/tpl`) is a small 2x2-grid `pfg` experiment (`pfg_grid_size: 2`, `pfg_grid_width: 25%`).
- `Data` (`/tony-test/data`) holds mock `input_number`/`input_select` helpers used to drive test scenarios.

All views are stored in `.storage` on `michael-dev` and snapshotted to the same JSON.

Tab order (PF3 is first):

| Order | Title |
|-------|-------|
| 0 | PF3 |
| 1 | PF4 |
| 2 | PFG1 |
| 3 | PFG |
| 4 | PFG2 |
| 5 | TPL |
| 6 | Data |
| 7 | Sankey |
| 8 | juWorkshop |
| 9 | Solar Assistant |
| 10 | glass |
| 11 | Weather |
| 12 | Solis Daily Energy Sankey |

PF3 and PF4 contain a single `custom:sunsynk-power-flow-card` in `cardstyle: lite` mode with a transparent background and the four-battery layout. PFG1, PFG, and TPL use `cardstyle: pfg`; PFG2 uses `cardstyle: pfg2`.

## Entity mapping

PF3 uses the main `battery` slot for the aggregate bank and `battery2`/`battery3`/`battery4` for physical packs 1-3.

| Card slot | Entity type | Entity ID |
|-----------|-------------|-----------|
| battery (main) | voltage | `sensor.totals_battery_voltage` |
| battery (main) | SOC | `sensor.totals_battery_state_of_charge` |
| battery (main) | power | `sensor.totals_battery_power` |
| battery (main) | current | `sensor.totals_battery_current` |
| battery2 | voltage | `sensor.batteries_1_voltage` |
| battery2 | SOC | `sensor.batteries_1_state_of_charge` |
| battery2 | power/current | `sensor.battery_1_calculated_power` / `sensor.battery_1_calculated_current` |
| battery3 | voltage | `sensor.batteries_2_voltage` |
| battery3 | SOC | `sensor.batteries_2_state_of_charge` |
| battery3 | power/current | `sensor.batteries_2_power` / `sensor.batteries_2_current` |
| battery4 | voltage | `sensor.batteries_3_voltage` |
| battery4 | SOC | `sensor.batteries_3_state_of_charge` |
| battery4 | power/current | `sensor.batteries_3_power` / `sensor.batteries_3_current` |

Pack 1 current and power are calculated from the total minus packs 2 and 3. The source package is `docs/home-assistant/configuration/packages/batteries_calculated.yaml`.

Inverter, solar, grid, and daily aggregate entities are in `docs/ssot/infrastructure/ssot.home-assistant.entities.yml`.

## Four-battery layout

- `battery` (main) is the aggregate status in the centre.
- `battery2` is top-right, `battery3` is bottom-left, `battery4` is bottom-right.
- Battery colour is `#00E676`.
- `battery.count` is 4.
- `show_remaining_energy` is `false` for battery2/battery4 and `true` for battery3.

## Which workflow? (decision tree)

- **Config-only change** (tile positions, `pfg_lines` anchors, images, entities, speed/max_power — anything the current bundle already supports): push live over websocket, no rebuild, no restart.
- **Code change** (new `pfg_*` key, new rendering, bugfix): rebuild, bump bundle version, deploy, restart `michael-dev`.
- **When unsure**, grep `src/cards/pfg-card.ts` / `src/cards/pfg2-card.ts` for the config key.

## Dashboard config workflow (no rebuild)

```bash
cat > /tmp/mutate.py <<'EOF'
def mutate(config):
    v = next(x for x in config["views"] if x.get("path") == "pfg2")
    c = v["cards"][0]
    c["pfg_lines"][0]["to"] = "6,3@bottom"   # example
EOF
set -a && source ~/.config/secrets/ha-michael-dev.env && set +a
python3 scripts/home-assistant/push-dashboard.py \
  "https://tony-dell.taila0626a.ts.net:8124" "tony-test" --mutate /tmp/mutate.py
./scripts/home-assistant/sync-ssot-from-live.sh
```

`push-dashboard.py` fetches `lovelace/config`, applies `mutate()`, and calls `lovelace/config/save`; the frontend refreshes automatically. Keep `mutate()` minimal — it edits the live config, so re-read the target view first and don't clobber concurrent edits.

## Card build and deploy workflow (new code)

1. Edit source in `/home/tony/CascadeProjects/sunsynk-power-flow-card/src/`.
2. Run `npm run build` in the repo root (~20s).
3. Bump the bundle version (see `ssot.home-assistant.cards.yml` for the latest) and `scp` `dist/sunsynk-power-flow-card.js` to `tony-dell:/home/tony/.config/michael-dev/www/sunsynk-power-flow-card-fork-v{version}.js`.
4. `sed` the old version to the new one in `/home/tony/.config/michael-dev/.storage/lovelace_resources`. A new filename is mandatory to beat browser/module cache.
5. Restart the dev container: `ssh tony-dell 'systemctl --user restart michael-dev.service'`. (`ha_reload_core` is **not** sufficient — `.storage` resources are only read on restart.)
6. Verify the bundle URL returns 200: `curl -sk https://tony-dell.taila0626a.ts.net:8124/local/sunsynk-power-flow-card-fork-v{version}.js`.
7. Verify at `https://tony-dell.taila0626a.ts.net:8124/tony-test/pf4`, `.../pfg`, `.../pfg2`.
8. Run `scripts/home-assistant/sync-ssot-from-live.sh` to snapshot `.storage/lovelace.tony_test` and update bundle version in `ssot.home-assistant.cards.yml`.
9. Copy the bundle and update `lovelace_resources` on `michael-ha` when the dev instance is verified.
10. Restart `michael-ha` with `ha core restart` or the REST service `homeassistant/restart`; `.storage` changes are only reflected after a restart.

## PFG / PFG2 grid cards

`cardstyle: pfg` and `pfg2` render an N x N tile grid (default 10 / 15; `pfg_grid_size` overrides). Tiles are addressed by 1-indexed `"r,c"` keys.

Tile config keys (all maps keyed by `"r,c"`):

| Key | Value | Notes |
|-----|-------|-------|
| `pfg_labels` | string | text label |
| `pfg_icons` | `mdi:*` name | per-tile icon |
| `pfg_images` | `/local/...` URL | `object-fit: cover`; tile clips overflow |
| `pfg_image_zoom` | number | `transform: scale(zoom)` on all image tiles |
| `pfg_values` | `{entity, scale?, decimals?, unit?}` | live sensor value |
| `pfg_sums` | `{entities[], scale?, decimals?, unit?}` | summed entities (e.g. PV1+PV2 in kW) |
| `pfg_spans` | number N | tile becomes N x N; covered cells skipped |
| `pfg_radius` | CSS radius | per-tile border-radius |
| `pfg_grid_width` | CSS width | e.g. `"25%"`, `"360px"` |

Render priority per tile: label > icon > image > sum/value > `r,c` coordinate text.

`pfg_lines` entries draw animated SVG flow lines between anchors:

```json
{ "from": "4,7@topright", "to": "6,7@bottomright", "entity": "sensor.inverters_1_grid_power", "speed": 0.8, "max_power": 6000 }
```

- Anchors: `"r,c"` (centre) plus `@top|bottom|left|right|topleft|topright|bottomleft|bottomright`. Anchors are span-aware — an edge/corner of an N x N tile uses the outer boundary.
- Optional `via` (intermediate anchor) or `elbow: "h"|"v"` for routed lines.
- `entity` sign sets direction (`>=0` flows from→to, `<0` reversed); `0`/unavailable pauses the dash animation and dims the line to 60%.
- Animation duration = `speed` / `clamp(|value| / max_power, 0.15, 1)` — more power, faster flow. `speed` default 0.8s, `max_power` default 1000 W.
- `color` overrides the entity status color (default `#FF9100`).
- Endpoints are raw anchor coordinates — an earlier `cellEdge()` inset was removed in v50 because it pushed endpoints into neighbouring cells.

Current PFG2 layout: PV images `2,2`/`2,4` (2x2 spans, `pv-tiles.jpg`), grid image `2,7` (2x2, `power-grid.jpg`), PV sum box `7,3` (2x2), inverter image centred at `8,8`, four animated lines bound to PV1/PV2/grid/PV-total entities.

## Battery status text and overlay avoidance

The combined battery status text is anchored at SVG coordinates `x=290, y=358` with classes `st13 st8` and `left-align`. Format:

```
{target}% | {current}%
```

Example: `20% | 80%`.

The card has separate SVG groups for plain and combined states:

- Plain: `Battery1_SOC`, `Battery2_SOC`, `Battery3_SOC`, `Battery4_SOC`
- Combined: `Battery*_SOC_Shutdown` and `Battery*_SOC_Program_Capacity`

To avoid the combined `{current}%` drawing over the plain `{current}%`, the plain group `<svg>` display expression must become `none` when the combined branch is visible. The condition is equivalent to:

```ts
data.inverterProg.show ||
(config.battery?.shutdown_soc && !config.battery?.shutdown_soc_offgrid)
```

Use the corresponding `config.battery2`, `config.battery3`, or `config.battery4` for each pack.

The charge/discharge runtime line is anchored at `x=290, y=393.7` with class `st3 left-align`. It has two branches:

- Discharge: `RUNTIME TO {target}% @22:20`
- Charge: `TO {target}% CHARGE @22:20`

The inactive branch is rendered with `fill: transparent`. For robust hiding, prefer `display: none` on the inactive parent `<svg>` group.

## Signed current and direction override

For a Solis inverter the raw battery power is negative during discharge. The PF3/PF4 cards set:

- `battery.invert_power: true` so the displayed power is positive while discharging.
- `entities.battery_current_direction` to `sensor.inverters_1_battery_direction` so the card explicitly resolves charge vs discharge.
- The resolved direction (`+1` for discharge, `-1` for charge) is then applied to the main battery power, runtime target, colour, and connector animation.

The overall battery box now renders a signed current on the first line, e.g. `53.0 V -34.2 A`, while pack currents keep their `show_absolute` display. If the direction entity is missing or `none`, the packs fall back to the raw sign from `invert_power` and the pack power entity.

## Visual verification with Playlive

The most reliable approach is a Playlive session attached to a Chrome profile that is already logged into the target HA instance (`playlive_create_playwright_chrome` or `playlive_create_chrome_live` against an existing CDP endpoint).

To use a headless Playwright session with a long-lived token:

1. Navigate to the instance origin, e.g. `https://tony-dell.taila0626a.ts.net:8124/`.
2. Store the token in `localStorage` as `hassTokens` using the format Home Assistant expects for `createLongLivedTokenAuth`:
   ```ts
   {
     access_token: '<TOKEN>',
     expires_in: 315360000,
     expires: Date.now() + 315360000000,
     hassUrl: 'https://tony-dell.taila0626a.ts.net:8124',
     clientId: null,
     refresh_token: ''
   }
   ```
3. Navigate to the view, e.g. `https://tony-dell.taila0626a.ts.net:8124/tony-test/pf4`.
4. Wait for the dashboard shell to load (`document.title` should show `Tony test – Home Assistant`).
5. Inspect the `sunsynk-power-flow-card` shadow root.
6. Search for `<text>` elements containing the suspect string and compare IDs, `x`/`y`, classes, `display`, and `fill`.
7. Look for duplicate `battery_soc_184` or `duration_text` IDs across different parent `<svg>` groups; this is expected and is not the overlay itself.
8. Confirm the parent `<svg>` group `display` is `none` for the inactive branch.

**Auth note:** Long-lived `HASS_TOKEN` values are for REST/websocket API calls and for the HA-MCP server. They can be used to authenticate the Home Assistant WebSocket (verified with `wss://tony-dell.taila0626a.ts.net:8124/api/websocket`), but they cannot bypass the browser OAuth redirect-URI check.

Browser login with username/password on `https://tony-dell.taila0626a.ts.net:8124` currently fails with `Invalid redirect URI`, so a headless Playwright browser may not fully render the Lovelace UI. Use a real logged-in Chrome profile when full visual inspection is required.

The `michael-dev` token is in `~/.config/secrets/ha-michael-dev.env`; the `michael-ha` token is in `~/.local/share/home-assistant-michael/ha-token`.

## Common failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Old card still shown after deploy | Browser cache or old resource path | Hard-refresh and confirm `lovelace_resources` points to the new bundle |
| `404` for `/local/...js` | Bundle not copied to `www/` or resource path wrong | Check `www/` contents and `.storage/lovelace_resources` |
| New card not loaded after restart | `michael-dev.service` failed or wrong config | Check `systemctl --user status michael-dev.service` and container logs |
| Combined text overlaps plain text | Plain `Battery*_SOC` `<svg>` not hidden | Add combined-visible display condition in `bat-elements.ts` |
| Fourth battery clipped | SVG canvas not wide/tall enough | Adjust card dimensions or viewBox in `compact-card.ts` / `ss4-card.ts` |
| `tony-test` tabs wrong order | `.storage/lovelace.tony_test` not synced | Edit the `.storage` file directly or sync from `michael-ha` |
| PF3 shows different entities than expected | Entity mapping drift | Compare live card config with `ssot.home-assistant.entities.yml` and re-sync |

## Re-syncing live state to the repo

Run:

```bash
./scripts/home-assistant/sync-ssot-from-live.sh
```

This script:

- Copies `michael-dev:/config/.storage/lovelace.tony_test` to `docs/home-assistant/dashboards/tony-test-current.json`.
- Reads the active card bundle version from `michael-dev:/home/tony/.config/michael-dev/www/` and updates `ssot.home-assistant.cards.yml`.
- Bumps `last_verified` dates in the relevant SSOT files.
- Runs `ssot-validate` and `ssot-validate-refs`.

**Bundle-version drift guard:** The script currently picks the newest `sunsynk-power-flow-card-fork-v*.js` by filename version. If old bundles with higher version numbers are left in `www/`, the script will report the wrong active version. Always clean up obsolete bundles or verify the value against `/config/.storage/lovelace_resources` before committing.

After review, commit the changes. The script never pushes; commit and push are manual.

## Token handling

Long-lived access tokens are stored in `~/.config/secrets/ha-{instance}.env` as `HASS_TOKEN=<token>` with `chmod 600`. Do not paste tokens into chat or commit them. See `docs/ssot/infrastructure/ssot.home-assistant.mcp.yml` for token file references.
