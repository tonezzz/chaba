# cast-cam — "show the security camera on the TV" scenario

Interactive runner for the voice/agent flow:

```
user: "show me the coffee corner camera on the TV"
  1. discover cast-capable TVs (HA media_player.*)
  2. user selects / confirms the TV
  3. check power state — off/standby → confirm before media_player.turn_on
     (Chromecast-class devices also wake on cast; androidtv reports real state)
  4. pick a camera (HA camera.* entities, friendly names)
  5. cast via camera/play_stream → media_player (HLS)
  6. verify cast player state + receiver app launched
```

## Run

```bash
python3 stacks/services/cast-cam/cast-cam.py scan          # TVs + cameras + states
python3 stacks/services/cast-cam/cast-cam.py run           # full interactive flow
python3 stacks/services/cast-cam/cast-cam.py run -c ip_cam_65 -t media_player.tony_tv_cast -y
```

Token: `HASS_TOKEN` env or `~/.config/secrets/home-assistant-token.env`.

## Current devices (2026-09-24)

- **TONY-TV** — androidtv `media_player.tony_tv` (power/app truth, TrueID box
  `com.truedmp.idtv`) + cast target `media_player.tony_tv_cast`.
- **TV-40C5000** — cast-only `media_player.tv_40c5000`.
- Cameras: `ip_cam_65` (Coffee corner), `xiaomi_c100`, `xiaomi_c201` (+_sd),
  `tony_dell_usb`. Desktops/album excluded.

## Interaction with cast-ha-panel.timer

The timer re-casts `input_select.tv_display` every 60s and reclaims the TV.
The script sets `tv_display=camera` for `ip_cam_65` (the timer's built-in
camera) so the cast is *sustained*; for other cameras either stop the timer
(`systemctl --user stop cast-ha-panel.timer`) or extend
`cast-ha-selected.sh` to read a camera `input_select` — TODO.

## Gotchas

- `camera.ip_cam_65` reports `unavailable` while its HLS stream is active —
  hidden from the picker on purpose; re-cast by entity_id with `-c`.
- `camera/play_stream` can take >8s — HA dispatches before responding; the
  script uses a 30s timeout for service calls.
- Cast players often sit at `idle` while HLS buffers — check
  `media_player.tony_tv` `app_name` flips to `mediashell` for ground truth.
- TV must reach `http://192.168.2.67:8123/api/hls/…` (LAN) — same LAN as dell.
- `input_select.tv_cast_target` option list currently only has "TONY-TV Cast";
  add TV-40C5000 there if it becomes a routine target.
