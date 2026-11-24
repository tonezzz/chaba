# Dispatch outcome — rk600-shutter-go-live (attempt 2, 2026-11-24)

## What I did

Attempt 1 left a verified-state runbook + raised the wind-unit board
request but produced no commits (merge-sweep fail). This run salvaged
that work and — because Tony had already answered the request ("Relabel
both to m/s") — applied the relabel live on michael-ha.

1. **Salvaged attempt-1 artifacts** into this worktree:
   `docs/ssot/jobs/home-assistant/2026-11-24-rk600-shutter-go-live-runbook.yml`
   (updated with the applied change; also corrected an earlier wrong
   claim — the input_number is YAML-defined, NOT editable via
   ha_config_set_helper).

2. **Applied the m/s relabel live on michael-ha** through the File
   editor add-on API (core_configurator ingress — works without SSH,
   which is broken fleet-wide):
   - `packages/rk600_modbus.yaml`: RK600 Wind Speed `kn` → `m/s`
   - `packages/rk600_shutter.yaml`: `input_number.shutter_wind_speed_min`
     `kn` → `m/s` (value stays 12.0 = 12 m/s ≈ 23 kt, per Tony's answer)
   - `packages/rika_rk600.yaml`: four "Wind Speed Meters" template
     sensors dropped the `/1.94384` kn→m/s conversion (raw register is
     already m/s — they were showing ~half), "RK600 Real Wind Speed"
     relabeled `kn` → `m/s`
   - Backups written: `packages/*.bak-devin-20261124`
   - `config_check` = valid, then `homeassistant.reload_all`
   - Verified live: `sensor.rk600_wind_speed` = 2.88 m/s,
     `input_number.shutter_wind_speed_min` = 12.0 m/s,
     `sensor.rk600_wind_speed_meters` = 2.88 m/s (now equals raw)
   - `input_boolean.shutter_control_armed` still `off` — correct, the
     armed gate stays manual until motors are proven.

3. **Repo updates**: `scripts/home-assistant/dev-shutter-tour.py`
   narration strings `kn` → `m/s` (6 spots, syntax-checked).

## Result

Card step 3 (wind-unit decision) is DONE — decided by Tony, applied and
verified live. Steps 1–2 (manual smoke, re-enable wind drivers) remain
physically gated on motor repair; step 4–5 unchanged. The card correctly
stays open/blocked.

## How to verify

- Live: `ha_get_state sensor.rk600_wind_speed` → unit `m/s`;
  `input_number.shutter_wind_speed_min` → `m/s`; dashboards show m/s
  automatically (helper/sensor units propagate).
- On-host files: `/config/packages/{rk600_modbus,rk600_shutter,rika_rk600}.yaml`
  on michael-ha; `*.bak-devin-20261124` siblings are the pre-change
  backups.
- Runbook: `docs/ssot/jobs/home-assistant/2026-11-24-rk600-shutter-go-live-runbook.yml`

lessons:
- michael-ha File editor add-on (core_configurator) is a full YAML
  read/write/exec path via ha_manage_app proxy when SSH is unavailable:
  GET /api/file?filename=<relative>, POST /api/save (form fields
  filename+text — object/JSON body fails "Missing filename or text"),
  POST /api/exec_command (shlex-split; repeated `command` keys — only
  the first is used, one command per call).
- `homeassistant.reload_all` via ha_call_service reloads YAML modbus +
  input_number + template sensors in one shot; check validity first
  with ha_get_system_health(include="config_check").
- "Relabel to m/s" on RK600 wind speed also required fixing four
  template sensors in packages/rika_rk600.yaml that divided by 1.94384
  assuming knots — a unit relabel is never just the two named entities.
- YAML-defined HA helpers show editable:false and are absent from
  ha_config_list_helpers; ha_get_entity 404s on them — don't trust
  "registry-backed" assumptions, check the actual YAML package files.
