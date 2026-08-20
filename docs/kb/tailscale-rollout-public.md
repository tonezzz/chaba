---
category: operations
---

# Phase 8 — Public Funnel Access and Active Connections (Delivered)

Tailscale Funnel is now hosted on `tony-dell` so the public landing page remains reachable even when `tony-omen` is offline.

- **Public URL (Funnel)**: `https://tony-dell.taila0626a.ts.net/`
- **Magic DNS (tailnet)**: `http://tony-dell:8082`
- **Home LAN**: `http://tony-dell.local:8082`

### Delivered components

1. **Funnel landing page** — `stacks/web/public/apps/tailscale-funnel/index.html` explains the three access paths (home, tailnet, public Funnel). A copy lives on `tony-dell` at `/home/tony/chaba-funnel/index.html` and is served by `chaba-funnel.service`.
2. **Network options banner** — `stacks/web/public/apps/index.html` shows the Funnel URL at the top of the apps directory.
3. **Active connections panel** — embedded in the Funnel landing page; fetches `/api/tailscale/connections` every 5 s and lists online, non-infrastructure peers with hostname, IP, OS, active/idle, and direct/relayed status.
4. **Funnel server** — `/home/tony/chaba-funnel/funnel-server.py` on `tony-dell` serves the static landing page and serves `tailscale status --json` over HTTP at `/api/tailscale/connections`, filtered to real devices (excludes Tailscale infrastructure/ingress nodes).
5. **Tailscale Funnel config** — `tailscale funnel --bg --yes 8082` on `tony-dell` publishes `https://tony-dell.taila0626a.ts.net/` and proxies `/` to `http://127.0.0.1:8082`.
6. **Systemd service** — `~/.config/systemd/user/chaba-funnel.service` on `tony-dell` makes the Funnel server persist across reboots and restart on failure.
7. **Health check integration** — `stacks/web/public/ssot.health.mobile.yml` `tailscale-funnel` service now points to `https://tony-dell.taila0626a.ts.net/apps/tailscale-funnel/`, with `funnel_unreachable` recovery actions on `tony-dell`.
8. **Workflow check** — `workflows/monitoring/universal-health-check.yml` `tailscale_check` block now tests Funnel reachability at `https://tony-dell.taila0626a.ts.net/apps/tailscale-funnel/`.

### Verify

```bash
# Public page and API
curl -I https://tony-dell.taila0626a.ts.net/
curl -s https://tony-dell.taila0626a.ts.net/api/tailscale/connections | python3 -m json.tool

# Systemd service
systemctl --user status chaba-funnel.service
```

