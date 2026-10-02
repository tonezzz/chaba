# cast-browser — voice-driven TV casting stack (tony-omen)

Persistent headless Chromium (`channel: chrome`) + Playwright that turns voice
commands into TV actions. Reached via `POST :8799/cmd` (tailnet) — Ada's
`tv_action` tool calls it directly (see ada-pi `home_assistant.py`); the legacy
path went through HA `rest_command.tv_action` (fire-and-forget — the response
was discarded, which is why clicks used to look successful when they weren't).

## Files

| file | deployed to | role |
|---|---|---|
| `cast-browser-server.mjs` | `~/.local/bin/` | HTTP server + Playwright driver |
| `cast-browser.service` | `~/.config/systemd/user/` | the server (user unit) |
| `cast-desktop@.service` | `~/.config/systemd/user/` | `cast-desktop@N` — x11grab→HLS for display `:N` |
| `cast-desktop-run.sh` | `~/.local/bin/` | ffmpeg x11grab wrapper (merges X auth cookies) |
| `cast-shots-http.service` | `~/.config/systemd/user/` | serves `~/.local/share/cast-shots` on `:8090` so the Chromecast can fetch screenshots |

Install on tony-omen: `./install.sh`, then `systemctl --user restart cast-browser`.

## Chain

```
Ada tv_action  ->  POST 100.75.102.88:8799/cmd
                 ->  playwright action on persistent page
                 ->  shotAndCast: page screenshot -> PNG -> HA media_player.play_media (image)
                 ->  TV shows the PNG — static, per-command, not a live page
```

- `nav <url>` loads the page headlessly then casts a screenshot.
- `click/scroll/press/type` act on the page, then re-screenshot + re-cast.
- `screenlive:workspace:N` / `tony-omen:workspace:N` switches the real desktop
  workspace (xdotool on `CAST_X_DISPLAY`, default `:0`) and casts the HLS
  stream from `cast-desktop@0`.

## Hard-won details

- **`X_DISPLAY` / workspace switching** — the desktop is `:0`, not `:1`.
  `set_workspace exit 1` = xdotool talking to a nonexistent display.
- **WebGL/Cesium** — Chrome needs the GPU process even for SwiftShader:
  `--disable-gpu` leaves Cesium half-initialized ("Error constructing
  CesiumWidget"). ANGLE-Vulkan on the real NVIDIA returns NULL for
  `powerPreference:"high-performance"`, which Cesium requires. Working args:
  `--no-sandbox --enable-unsafe-swiftshader`.
- **Click labels must match visible text** — e.g. GEV's button says
  "CONTACTS"; "Live Contacts" (the context-mode name) times out.
- **Click on missing element ≈ 36s** — `scrollIntoViewIfNeeded` (30s) +
  locator `click` (6s) timeouts stack.
- ACL: `aclCheck` per command — desktop sources (`screenlive:`, `tony-omen:`)
  require `speaker` identity; owner-locked to `person.tony`.
- Watchdog: `page watchdog` reloads the page every ~10min on nav errors —
  with a dead page (e.g. `chrome-error://` after DNS failure) every command
  keeps failing until something navs away.
- The error channel works end-to-end now: cast-browser `{err:...}` →
  ada-pi raises → Ada says it failed instead of claiming success.
