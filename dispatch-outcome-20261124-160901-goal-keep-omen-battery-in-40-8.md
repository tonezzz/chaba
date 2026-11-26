# Dispatch outcome — omen-battery-charge-policy (attempt 2)

## What changed

- **HA automation DEPLOYED on tony-ha** (the host's own HA at 127.0.0.1:8123):
  `automation.omen_plug_charge_band_85_45` — "Omen plug: charge band (85/45)",
  state `on`, in `~/.config/home-assistant/packages/system-managed.yaml`
  (managed group per ssot.home-assistant.automations.yml). HA config git
  commit `bd17c99`.
- Behavior: plug OFF at battery >=85 (fresh telemetry only), ON at <=45,
  fail-open ON on telemetry stale >10m/>15m or battery <20%, 5-min watchdog
  band-check, persistent_notification + notify.mobile_app_tony_ip on
  <25%/15min and <20%.
- **Dormant-safe design**: every plug action is guarded by
  `states('switch.omen_plug') in ['on','off']`, so the automation is inert
  until the plug entity exists, then activates automatically. Battery
  critical/low alerts fire regardless. Verified: `automation.reload` via
  websocket succeeded, entity present, manual `automation.trigger` ran clean,
  zero omen_plug errors in HA log.
- Chaba worktree commit `53df4a4` on `dispatch/20261124-160901-...`:
  - `docs/ssot/jobs/home-assistant/2026-11-24-omen-battery-charge-band.yml`
    — recovered from attempt-1 commit `91b39c3`, updated to deployed status
    with full deploy/auth/integration notes.
  - `docs/ssot/infrastructure/ssot.home-assistant.automations.yml` —
    registered the new managed automation in the inventory.
- Board request raised (`automation-is-deployed-and-live-on-tony-e51f7a`):
  plug purchase+pair is the only remaining physical step, with plug-type
  recommendation (CozyLife > Tuya > Sonoff).

## Result / state

- Tony's A-vs-B answer ("A — plug + automation now") was actioned: the
  automation half is done and live.
- Remaining: a smart plug must be bought (~THB 250-400), paired, and its
  switch entity must be `switch.omen_plug` with power-on state ON; then the
  Omen AC brick moves onto it. Battery is at 61% — in-band already.
- Recovered attempt-1 work via local branch
  `dispatch/20261124-151835-...` commit `91b39c3` (its worktree had 1
  unrelated dirty file, left untouched).

## How to verify

- `ssh tony-omen` → HA REST/websocket: `automation.omen_plug_charge_band_85_45` = on.
- `grep omen ~/.config/home-assistant/home-assistant.log` → no errors.
- After plug pairing: `switch.omen_plug` appears → next watchdog/trigger
  tick exercises the band logic; watch logbook for "charge-band" entries.

## Auth gotcha discovered (worth remembering)

`~/.config/secrets/home-assistant-token.env` on omen = `svc-chaba-scripts`,
**non-admin**: GET works, ALL service calls 401 (REST POST + websocket
`call_service`). `~/.config/secrets/telemetry-ha-push.env`
`HA_LONG_LIVED_TOKEN` = Tony, admin/owner — use it for service calls, and
`export` it before python (file has no `export`).

## lessons:

- HA on tony-omen: REST POST /api/services 401s for non-admin LLATs — use websocket `call_service` with the admin token from `telemetry-ha-push.env` (export it; env files lack `export`).
- Deploying a dormant-safe automation (entity-exists template guards on every action) lets safety guards go live before their hardware exists — no error spam, auto-activates later.
- Managed HA automations belong in `packages/system-managed.yaml` (not automations.yaml); `automation.reload` picks them up, no restart needed.
- Dispatch attempt recovery: prior attempt's branch/commit (`91b39c3`) was still local on the same host — `git checkout <sha> -- <file>` resurrects staged work fast.
- Plug ecosystem on tony-ha is mixed (cozylife_local, command_line+tinytuya, sonoff, official tuya entry); `tuya-control.py` status polls were exit-2 in logs at deploy time — CozyLife path is the cleanest for new plugs.
