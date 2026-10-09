# gesture-relay — WS fan-out for the iPhone→TV hand-gesture rebuild

Quadlet `gesture-relay.service` (`localhost/gesture-relay`, publish on the
host's tailscale IP only). Tiny asyncio websockets fan-out — same shape as
`../gev-gemini` but dumber: no model, no tools, no command endpoint.

## Wire format

- `ws://<ip>:8794/ws?role=controller` — the iPhone camera page
  (`/apps/gesture/`). Emits `{type:"gesture", x, y, wx, wy}` at ~20 Hz
  (normalized 0–1, index-tip + wrist, X mirror-flipped) plus edge events in
  the same frame shape with `action: "pinch" | "fist_start" | "fist_end"`.
- `ws://<ip>:8794/ws?role=screen` — the TV/display page
  (`/apps/gesture/screen`). Receives controller frames verbatim.
- Anything else on `/ws` (no `role=controller`) is treated as a screen.
- Every client also receives `{type:"peer", controllers, screens, ts}`
  presence events on join/leave — pages use it for the connection status
  line.
- `GET /health` → `200 {"ok":true,"controllers":N,"screens":N}` on the same
  port (websocket `process_request` hook).

The relay is deliberately blind — no auth (tailnet edge + Caddy is the
boundary), no schema validation, no buffering. Gesture frames are ephemeral.

## Edge path

```
iPhone Safari ──wss──> tony-dell tailnet /apps/gesture-live/ws?role=controller
                                                        │ Caddy handle_path
                                                        ▼
TV browser    <─wss── /apps/gesture-live/ws?role=screen   100.68.142.13:8794
```

Caddy block is `custom: true` route `gesture-live` in
`docs/ssot/infrastructure/ssot.routes.yml` (rendered by
`scripts/render-routes.py --caddy`).

## Deploy / refresh (on tony-dell)

```bash
cd <chaba checkout>
podman build -t localhost/gesture-relay:latest stacks/tony-dell/gesture-relay
bash stacks/tony-dell/gesture-relay/install.sh   # renders tailnet PublishPort, starts
```

`install.sh` mirrors `stacks/services/xmeye-vms/install.sh`: renders
`PublishPort=<tailscale-ip>:8794:8794` into
`~/.config/containers/systemd/gesture-relay.container`, daemon-reloads, and
restarts the generated `gesture-relay.service`.

## Smoke

```bash
python3 live-check.py                                  # ws://127.0.0.1:8794
python3 live-check.py --url wss://tony-dell.taila0626a.ts.net/apps/gesture-live/ws
```

Connects a screen + a controller, asserts fan-out and peer events, checks
`/health`. No external services needed.

NOTE: `requirements.txt` pins `websockets==16.1.1` (the asyncio API —
`process_request(connection, request)` + `connection.respond`). gev-gemini's
unpinned-deps lesson applies — bump deliberately.
