# Dispatch outcome — omen-battery-charge-policy (attempt 3 / dispatch 192853)

## What this run did

Re-verification pass only — the prior attempt (dispatch 160901, merged as
`5eb4bc7a`) already deployed everything deployable. This session confirmed
the deployed state is still healthy and that nothing new unblocked the
remaining physical step.

## Verified live on tony-ha (127.0.0.1:8123, admin LLAT from
`~/.config/secrets/telemetry-ha-push.env`)

- `automation.omen_plug_charge_band_85_45` = **on**, watchdog firing every
  5 min (`last_triggered` 2026-11-24T12:35Z = 19:35 ICT at check time).
- Zero `omen_plug`/`charge_band` errors in `~/.config/home-assistant/
  home-assistant.log` (only a pre-existing unrelated
  `mac_plug_charge_band_80_60` UndefinedError from 2026-11-23 — the macbook
  automation's own `last_updated` edge case, already noted in the job doc).
- `switch.omen_plug` does **not** exist — no plug paired since deploy.
- Full `switch.*` census unchanged: `plakkaaaef_local` (coffee, on),
  `palhawetiiyng_local` (bedside, on), `plug_tv` (off), `mac_plug`
  (unavailable/offline), `smart_socket_schedule_enabled` (fan-plug schedule
  helper, not a spare outlet). **No spare plug appeared — option A still
  needs the ~THB 250-400 purchase.**
- Battery telemetry fresh: `sensor.tony_omen_battery_level` = 61,
  `binary_sensor.tony_omen_telemetry_fresh` = on, omen online.

## Notable observation (non-blocking)

`/sys/class/power_supply/BAT0/status` = **"Not charging"** at 61% while
`ADP1/online` = 1 (AC attached). The Omen's EC is not actively charging at
mid-band on AC — either firmware charge management or a gauge quirk.
Does not affect the design: when the plug lands and battery drops ≤45%,
plug ON resumes the charge path; ≥85% cuts it. If "Not charging" persists
at 100% after plug install, that's an EC/firmware behavior to revisit —
worth one glance during the first live cycle.

## Blocker (unchanged)

Board request `automation-is-deployed-and-live-on-tony-e51f7a` is still
**open** — Tony's plug choice (CozyLife recommended / Tuya / Sonoff /
already-have-one). `$TASK_DIR/answers.jsonl` absent; no answer arrived
during this run. Card correctly stays in review (`awaiting_action: true`).

## Deliverables (all already on origin/master via 5eb4bc7a)

- `docs/ssot/jobs/home-assistant/2026-11-24-omen-battery-charge-band.yml`
  — full job doc: investigation evidence, options analysis, deployed
  automation spec, runbooks for A (plug) and B (BIOS check).
- `docs/ssot/infrastructure/ssot.home-assistant.automations.yml` —
  inventory entry for the managed automation.
- Live HA: `automation.omen_plug_charge_band_85_45` in
  `~/.config/home-assistant/packages/system-managed.yaml` (HA git bd17c99).

## How to verify

- `curl -H "Authorization: Bearer $HA_LONG_LIVED_TOKEN" \
  http://127.0.0.1:8123/api/states/automation.omen_plug_charge_band_85_45`
  on tony-omen → state `on`.
- After plug pairing + `switch.omen_plug` exists: watch logbook for
  "charge-band" entries; battery should oscillate 45-85%.

## lessons:

- A re-dispatch on an already-deployed card can be pure verification: check
  the open board request + live entity state first; if unchanged, a short
  comms + outcome doc is the correct close, not new work.
- `switch.smart_socket_schedule_enabled` looks plug-ish by name but is a
  fan-plug *schedule helper* (Thai friendly name) — check `friendly_name`
  before counting a switch as a usable outlet.
- HP Omen EC reports BAT0 status "Not charging" at 61% on AC — mid-band AC
  states are not trustworthy as a charge indicator; capacity % is.
