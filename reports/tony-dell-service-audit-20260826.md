# tony-dell Service Audit

**Date:** 2026-08-26
**Audited by:** assistant
**Host:** tony-dell (100.68.142.13)

## Executive Summary

tony-dell is running 52 user systemd services and 21 Podman containers. It is the primary headless host for persistent web/API/datastore services. Several low-latency MCP servers are still running on tony-omen and should be migrated to tony-dell to satisfy the `Stabilize tony-dell as the headless primary host` focus.

## systemd --user services (running)

| Service | Type | Notes |
|---|---|---|
| at-spi-dbus-bus.service | system | Accessibility bus |
| camera-panel.service | custom | Camera Control Panel |
| chaba-funnel.service | custom | Tailscale Funnel landing page and API |
| chrome-cdp-visible.service | custom | Visible Chrome with CDP |
| dbus.service | system | User D-Bus |
| dconf.service | system | User preferences |
| dnsmasq-postgre.service | custom | Local DNS alias for PostgreSQL |
| evolution-* | system | Evolution components (x3) |
| filter-chain.service | system | PipeWire |
| gemini-ollama-proxy.service | podman | Gemini-Ollama embedding proxy |
| gnome-keyring-daemon.service | system | Keyring |
| gpu-queue-processor.service | podman | GPU queue worker |
| gpu-queue.service | podman | GPU queue manager |
| gvfs-* | system | Virtual filesystem (x8) |
| helm.service | custom | Helm Web UI |
| home-assistant.service | podman | Home Assistant |
| mcp-debug-cors.service | custom | mcp_debug CORS endpoint for chaba.h3 |
| mcp-link-monitor.service | custom | TCP/IP link monitor |
| mcp-rview-oauth-proxy.service | custom | RView OAuth proxy |
| mcp-rview.service | custom | RView stdio proxy |
| mddb-panel.service | podman | MDDB panel container |
| mddb.service | podman | MDDB container |
| mpris-proxy.service | system | Bluetooth mpris |
| obex.service | system | Bluetooth OBEX |
| pipewire-pulse.service | system | PipeWire PulseAudio |
| pipewire.service | system | PipeWire |
| plasma-* | system | KDE components (x2) |
| raceman-php.service | podman | Raceman PHP |
| raceman-web.service | podman | Raceman Web |
| rclone-gdrive.service | custom | Google Drive mount |
| redis.service | podman | Redis container |
| rview-api.service | podman | RView API |
| rview-live.service | podman | RView Live API |
| snap.snapd-desktop-integration | system | Snap integration |
| status-data-api.service | custom | Status Data API |
| wireplumber.service | system | WirePlumber |
| xdg-desktop-portal* | system | Portals (x4) |
| xdg-document-portal.service | system | flatpak document portal |
| xdg-permission-store.service | system | Permission store |
| xvfb-99.service | custom | Virtual X display :99 |
| yomi-api.service | podman | Yomi API server |

Total: 52 active user services.

## Podman containers (running)

| Container | Image | Status |
|---|---|---|
| chaba-postgres-16 | pgvector/pgvector:pg16 | Up 9 days |
| redis | redis:7.4-alpine | Up 9 days |
| mddb-panel | tradik/mddb:panel-latest | Up 9 days |
| raceman-php | chaba-raceman-raceman-php:latest | Up 9 days |
| raceman-web | nginx:alpine | Up 9 days |
| weaviate | semitechnologies/weaviate:latest | Up 9 days |
| status-data-api | localhost/status-data-api:latest | Up 8 days |
| mddb-gemini-test | tradik/mddb:latest | Up 7 days |
| mddb-ollama-test | tradik/mddb:latest | Up 7 days |
| bserver | localhost/bserver:latest | Up 6 days |
| web | caddy:latest | Up 25 hours |
| trade-api | trade-trade-api:latest | Up 6 days |
| rview-api | localhost/rview-api:latest | Up 4 days (healthy) |
| yomi-api | node:22-slim | Up 3 days |
| helm | localhost/web-helm:latest | Up 3 days |
| rview-live | localhost/rview-live:latest | Up 25 hours (healthy) |
| mddb | tradik/mddb:latest | Up 22 hours |
| gpu-queue-processor | node:22-alpine | Up 21 hours |
| gpu-queue | node:22-alpine | Up 20 hours (healthy) |
| gemini-ollama-proxy | node:22-alpine | Up 20 hours (healthy) |
| home-assistant | homeassistant/home-assistant:stable | Up 2 hours (unhealthy) |

Total: 21 active Podman containers.

## Missing persistent units (to be migrated from tony-omen)

1. **mcp-debug-sse.service** — The SSE MCP server for `mcp_debug` is currently on tony-omen at `http://tony-omen:9101`. It should run on tony-dell to keep the MCP entrypoint on the headless primary host.
2. **mcp-health.service** — `mcp-health` is a Python stdio/SSE server. Running it on tony-dell would centralize health checks on the same host as the other persistent services.
3. **mcp-focus.service** — `mcp-focus` is currently an stdio MCP server. Making it a persistent SSE/stdio service on tony-dell would allow remote assistants to query the canonical focus state over the network.
4. **PostgreSQL persistent unit** — PostgreSQL runs in a Podman container (`chaba-postgres-16`) which is persistent, but there is no `systemd` Quadlet or user unit explicitly backing it. A `.container` Quadlet should be added to SSOT.
5. **yomi-process.service** — Yomi processing may still run on tony-omen; verify whether the processor is co-located with `yomi-api.service`.

## Recommendations

1. Add `mcp-debug-sse.service`, `mcp-health.service`, and `mcp-focus.service` as `systemd --user` units on tony-dell.
2. Convert `chaba-postgres-16` from `podman run` to a rootless Quadlet unit so it is managed by systemd.
3. Add tony-dell health checks to `ssot.health` so the `mcp-health` server can monitor the host directly.
4. Verify Tailscale Funnel/Serve mappings on tony-dell for the new MCP services.
