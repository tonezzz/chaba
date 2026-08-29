---
category: operations
---

# Phase 8 — Public Funnel Access and Active Connections (Delivered)

> **Update (2026-08-28):** Port 8444 has been reassigned to `ha-live` (Home Assistant Gemini Live bridge). The original chaba-funnel landing page on 8444/8082 is decommissioned. The public Tailscale Funnel is now `https://tony-dell.taila0626a.ts.net:8444/`, proxied to `127.0.0.1:9005`.

Tailscale Funnel on `tony-dell` now terminates port 8444 and proxies to `ha-live` (Home Assistant / Gemini Live bridge) instead of the legacy `chaba-funnel` landing page.

- **Public URL (Home Assistant Live / Gemini bridge)**: `https://tony-dell.taila0626a.ts.net:8444/`
- **Local target**: `127.0.0.1:9005` (`ha-live/bridge.py`)
- **Magic DNS (tailnet)**: `http://tony-dell:8082` (legacy chaba-funnel; no longer active)
- **Home LAN**: `http://tony-dell.local:8082` (legacy chaba-funnel; no longer active)
- **OAuth proxy**: `https://tony-dell.taila0626a.ts.net/` (port 443, `127.0.0.1:9004`)

### Delivered components

1. **ha-live bridge** — `~/.config/home-assistant/ha-live/bridge.py` on `tony-dell` exposes the Gemini Live push-to-talk bridge over `127.0.0.1:9005`.
2. **Tailscale Funnel config** — `tailscale funnel --bg --yes --https=8444 127.0.0.1:9005` on `tony-dell` publishes `https://tony-dell.taila0626a.ts.net:8444/` and proxies `/` to `http://127.0.0.1:9005`. Port 443 remains the mcp-rview OAuth proxy.
3. **Systemd service** — `~/.config/systemd/user/ha-live.service` on `tony-dell` keeps the bridge running across reboots.
4. **Health check integration** — `docs/ssot/infrastructure/ssot.health.home.tailscale.yml` `ha-live` service points to `https://tony-dell.taila0626a.ts.net:8444/`, with recovery actions on `tony-dell`.
5. **Decommissioned** — `chaba-funnel.service`, `/home/tony/chaba-funnel/`, and the landing page on 8444/8082 are removed. The static `stacks/web/public/apps/tailscale-funnel/index.html` remains for historical reference only.

### Verify

```bash
# Public bridge
curl -I https://tony-dell.taila0626a.ts.net:8444/
curl -s -o /dev/null -w '%{http_code}' https://tony-dell.taila0626a.ts.net:8444/

# Local bridge
ss -tlnp | grep 9005
curl -s http://127.0.0.1:9005/ | head -5

# Systemd service
systemctl --user status ha-live.service
```

