---
category: operations
---

# Phase 8 — Public Funnel Access and Active Connections (Delivered)

Tailscale Funnel is now hosted on `tony-dell` so the public landing page remains reachable even when `tony-omen` is offline.

- **Public URL (Funnel)**: `https://tony-dell.taila0626a.ts.net:8444/`
- **Magic DNS (tailnet)**: `http://tony-dell:8082`
- **Home LAN**: `http://tony-dell.local:8082`
- **OAuth proxy**: `https://tony-dell.taila0626a.ts.net/` (port 443, `127.0.0.1:9004`)

### Delivered components

1. **Funnel landing page** — `stacks/web/public/apps/tailscale-funnel/index.html` explains the three access paths (home, tailnet, public Funnel). A copy lives on `tony-dell` at `/home/tony/chaba-funnel/index.html` and is served by `chaba-funnel.service`.
2. **Network options banner** — `stacks/web/public/apps/index.html` shows the Funnel URL at the top of the apps directory.
3. **Active connections panel** — embedded in the Funnel landing page; fetches `/api/tailscale/connections` every 5 s and lists online, non-infrastructure peers with hostname, IP, OS, active/idle, and direct/relayed status.
4. **Funnel server** — `/home/tony/chaba-funnel/funnel-server.py` on `tony-dell` serves the static landing page and serves `tailscale status --json` over HTTP at `/api/tailscale/connections`, filtered to real devices (excludes Tailscale infrastructure/ingress nodes).
5. **Tailscale Funnel config** — `tailscale funnel --bg --yes --https=8444 8082` on `tony-dell` publishes `https://tony-dell.taila0626a.ts.net:8444/` and proxies `/` to `http://127.0.0.1:8082`. Port 443 remains the mcp-rview OAuth proxy.
6. **Systemd service** — `~/.config/systemd/user/chaba-funnel.service` on `tony-dell` makes the Funnel server persist across reboots and restart on failure.
7. **Health check integration** — `docs/ssot/infrastructure/ssot.health.mobile.yml` `chaba-funnel` service now points to `https://tony-dell.taila0626a.ts.net:8444/health`, with `funnel_unreachable` recovery actions on `tony-dell`.
8. **Workflow check** — `workflows/monitoring/universal-health-check.yml` `tailscale_check` block now tests Funnel reachability at `https://tony-dell.taila0626a.ts.net:8444/apps/tailscale-funnel/`.

### Verify

```bash
# Public page and API
curl -I https://tony-dell.taila0626a.ts.net:8444/
curl -s https://tony-dell.taila0626a.ts.net:8444/api/tailscale/connections | python3 -m json.tool

# Systemd service
systemctl --user status chaba-funnel.service
```

