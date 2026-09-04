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

Tab order (PF3 is first):

| Order | Title |
|-------|-------|
| 0 | PF3 |
| 1 | SS4 |
| 2 | Sankey |
| 3 | juWorkshop |
| 4 | Sunsynk |
| 5 | SS2 |
| 6 | Solar Assistant |
| 7 | flow1 |
| 8 | glass |
| 9 | Weather |
| 10 | Test2 |
| 11 | SS3 |
| 12 | Solar Assistant Power Flow |
| 13 | Solis Daily Energy Sankey |

PF3 contains a single `custom:sunsynk-power-flow-card` in `cardstyle: lite` mode with a transparent background and the four-battery layout.

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

## Card build and deploy workflow

1. Edit source in `/home/tony/CascadeProjects/sunsynk-power-flow-card/src/`.
2. Run `npm run build` in the repo root.
3. Note the new bundle version (e.g. `v29`).
4. Copy `dist/sunsynk-power-flow-card.js` to `tony-dell:/home/tony/.config/michael-dev/www/sunsynk-power-flow-card-fork-v{version}.js`.
5. Update the Lovelace resource in `/home/tony/.config/michael-dev/.storage/lovelace_resources` to `/local/sunsynk-power-flow-card-fork-v{version}.js`.
6. Restart the dev container: `systemctl --user restart michael-dev.service`.
7. Verify at `https://tony-dell.taila0626a.ts.net:8124/tony-test/pf3`.
8. Run `scripts/home-assistant/sync-ssot-from-live.sh` to snapshot `.storage/lovelace.tony_test` and update bundle version in `ssot.home-assistant.cards.yml`.

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

## Visual verification with Playlive

1. Open the PF3 URL in Playlive or browser.
2. Inspect the `sunsynk-power-flow-card` shadow root.
3. Search for `<text>` elements containing the suspect string.
4. Compare IDs, `x`/`y`, classes, `display`, and `fill`.
5. Look for duplicate `battery_soc_184` or `duration_text` IDs across different parent `<svg>` groups; this is expected and is not the overlay itself.
6. Confirm the parent `<svg>` group `display` is `none` for the inactive branch.

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

After review, commit the changes. The script never pushes; commit and push are manual.

## Token handling

Long-lived access tokens are stored in `~/.config/secrets/ha-{instance}.env` as `HASS_TOKEN=<token>` with `chmod 600`. Do not paste tokens into chat or commit them. See `docs/ssot/infrastructure/ssot.home-assistant.mcp.yml` for token file references.
