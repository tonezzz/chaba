# TV casting runbook — tony-ha

SSOT: `docs/ssot/infrastructure/ssot.home-assistant.automations.yml`
Decision: `docs/ssot/decisions/ssot.technical-decisions.yml` → `tv-casting-groups`

## The cast paths (all verified 2026-09-24)

| What | Path | Notes |
|---|---|---|
| Camera live view | `camera/play_stream` → `media_player.tony_tv_cast` (HLS) | source cam must be `idle`, not `unavailable` |
| Dashboard/view | `cast-ha-panel.timer` (60s) → `cast-ha-selected.sh` → `cast-browser :8799` screenshot → cast PNG | driven by `input_select.tv_display` |
| noVNC/VMS | `input_select.tv_display=vms` → cast-browser nav → `http://tony-dell/apps/vnc/vnc.html` | stale: points at old dell path; update to `/apps/vms/` |
| Desktop | `cast-desktop@1.service` → HLS | CPUQuota 60% |
| YouTube | `youtube_*` automation chain → `script.cast_youtube_tv` | picker/queue/search helpers |
| TTS speak | `tts.speak` on `media_player.tony_tv_cast` | e.g. speak_hello event |
| IR control | `script.tv_*` via `remote.tony_tv` | power/vol/nav |

## TVs

| Entity | Role | Power check |
|---|---|---|
| `media_player.tony_tv` | androidtv — real state/app | `state`, `app_name` |
| `media_player.tony_tv_cast` | cast target | cast session state |
| `media_player.tv_40c5000` | 2nd cast target | state only |
| `switch.plug_tv` | smart plug | hard cut (last resort) |

## Safety model — IMPLEMENTED 2026-09-24

Managed bundle: `/config/packages/cast-safety.yaml` (host path
`~/.config/home-assistant/packages/cast-safety.yaml`), loaded via
`homeassistant.packages` in `configuration.yaml`. YAML-defined = visible in UI
but **not editable** there (toggleable only). Changes go through git.

| Layer | Entity / mechanism | Behavior |
|---|---|---|
| Kill switch | `input_boolean.cast_enabled` | `cast-ha-selected.sh` and `cast-cam.py` exit when `off`; auto-tripped by rate limit |
| Rate limit | `counter.cast_starts` + `cast_guard_*` | `>6` cast starts in a 10-min window → `tv_display=off`, `cast_enabled=off`, `script.cast_cleanup`, notify |
| Source liveness | `cast_guard_source_lost` + script check | selected `input_select.tv_camera` → `unavailable` while `tv_display=camera` → cleanup + notify; timer script also skips dead sources |
| Idle cleanup | `cast_idle_shutdown` + `cast_activity_reset` | moved to the package (same ids); `cast_powered_by_us` still gates cleanup to our sessions |
| Host audit | `audit-cast.timer` → `~/.local/bin/audit-cast.sh` | every 5 min, HA-independent: kills ffmpeg with no owning unit or >150% CPU, restarts cast-browser >3GiB RSS, kills orphan x11vnc/websockify, stops cast units when `cast_enabled=off`. Log: `~/.local/share/cast-audit.log` |
| Physical | `switch.plug_tv` | hard power cut — manual last resort only, audit never touches it |

Camera selection: `input_select.tv_camera` (managed) replaces the old
`ip_cam_65` hardcode — `cast-ha-selected.sh` and `cast-cam.py` both use it.

Deferred (see SSOT `audit_hooks.deferred_guards`): session cap, flap
detection, `cast_enabled` in editable YouTube/assist paths.

## Kill chain (runaway response order)

1. `input_select.tv_display = off` — stops the 60s re-cast loop
2. `input_boolean.cast_enabled = off` — blocks all managed cast paths
   (host audit will also stop lingering cast units on next 5-min pass)
3. `script.cast_cleanup` — ends the receiver session
4. `systemctl --user stop cast-ha-panel.timer cast-browser.service cast-desktop@1.service`
5. `switch.plug_tv off` — physical cut if software is wedged

## Review checklist — resolved 2026-09-24

- [x] `packages/` mechanism approved and live
- [x] `cast_enabled` master switch implemented (managed paths)
- [x] Rate limit: 6 starts / 10 min; session cap + flap deferred
- [x] `input_select.tv_camera` added — any listed camera sustained by timer
- [ ] Decide fate of `script.tv_cast_*` (unavailable legacy — remove?)
- [ ] Update `vms` cast key to `/apps/vms/` — **blocked**: the page requires
      `Tailscale-User-Login`, headless cast-browser can't pass the gate;
      needs a loopback-unauthed path or stays on legacy `/apps/vnc/`
