# ha-live

Home Assistant Live bridge — Gemini Live voice assistant inside the `home-assistant` container.

## Files

- `bridge.py` — WebSocket bridge (host `0.0.0.0:9005`) that proxies browser audio to the Gemini Live API and exposes HA-MCP tools.
- `index.html` — Standalone voice UI for the bridge.
- `restart.sh` — Manual restart helper.
- `ha-live.service` — User systemd service that runs the bridge via `podman exec` inside the `home-assistant` container.

## Deployment

On `tony-dell`:

```bash
mkdir -p ~/.config/home-assistant/ha-live
mkdir -p ~/.config/systemd/user
# copy bridge.py, index.html, restart.sh to ~/.config/home-assistant/ha-live/
# copy ha-live.service to ~/.config/systemd/user/ha-live.service
systemctl --user daemon-reload
systemctl --user enable --now ha-live
```

## Tunnels

- Tailscale Funnel: `https://tony-dell.taila0626a.ts.net:8444/`
- WebSocket: `wss://tony-dell.taila0626a.ts.net:8444/ws`
