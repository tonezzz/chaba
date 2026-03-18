# idc1 host config

This document is the **operator view** of host-level configuration for the `idc1` machine.

Rules:

- No secrets in this file.
- Prefer documenting **effective runtime endpoints**, ports, and the authoritative config locations.

## Edge reverse proxy (Caddy)

On idc1, **system Caddy** is the single TLS terminator and the source of truth for public routing.

- Service:
  - `caddy` (systemd)
- Config file:
  - `/etc/caddy/Caddyfile`
- Logs:
  - `sudo journalctl -u caddy -n 200 --no-pager`
- Validate + reload:
  - `sudo caddy validate --config /etc/caddy/Caddyfile`
  - `sudo systemctl reload caddy`

### Domains routed by Caddy (relevant to Assistance)

For Jarvis (idc1-assistance), Caddy should serve:

- `assistance.idc1.surf-thailand.com`
- optionally also `assistant.idc1.surf-thailand.com` (alias / legacy)

### Assistance routing (HTTP + WebSocket)

Caddy routes into the `idc1-assistance` stack via loopback-only host binds:

- Jarvis backend:
  - `127.0.0.1:18018` (container port 8018)
- Jarvis frontend:
  - `127.0.0.1:18080` (frontend container)

Required paths:

- WebSocket:
  - public: `wss://assistance.idc1.surf-thailand.com/jarvis/ws/live`
  - proxy behavior:
    - match `path /jarvis/ws/*`
    - strip `/jarvis` prefix
    - reverse proxy to `127.0.0.1:18018` (backend serves `/ws/live`)

- Backend HTTP API:
  - public: `https://assistance.idc1.surf-thailand.com/jarvis/api/...`
  - proxy behavior:
    - match `handle_path /jarvis/api/*`
    - reverse proxy to `127.0.0.1:18018`
  - used for:
    - `GET /jarvis/api/logs/ws/today?max_bytes=...`
    - `GET /jarvis/api/logs/ui/today?max_bytes=...`
    - `POST /jarvis/api/logs/ui/append`
    - `POST /jarvis/api/jarvis/memo/add`

- Frontend:
  - public: `https://assistance.idc1.surf-thailand.com/jarvis/`
  - proxy behavior:
    - match `handle_path /jarvis/*`
    - reverse proxy to `127.0.0.1:18080`

### Known failure mode: TLS handshake “internal error”

If `openssl s_client -servername assistance.idc1.surf-thailand.com ...` fails with a TLS alert, the usual cause is:

- Caddy has **no site block** (or no cert automation) for that SNI name.

Fix by adding a site definition for `assistance.idc1.surf-thailand.com`, or making it an alias on the existing `assistant...` site.

Example (alias):

- `assistant.idc1.surf-thailand.com, assistance.idc1.surf-thailand.com { ... }`

Then reload Caddy.

## Stacks on idc1

Compose stacks live under:

- `stacks/`

Assistance stack:

- `stacks/idc1-assistance/CONFIG.md`

