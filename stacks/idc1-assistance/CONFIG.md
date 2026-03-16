# idc1-assistance stack config

This document describes the **effective runtime configuration** and operator workflows for the `idc1-assistance` stack (Jarvis backend + frontend + MCP bundle + related services).

Rules:

- No secrets in this file.
- Prefer documenting **effective bind ports/URLs** that operators use.
- Compose defaults do not override values configured in **Portainer stack env**.

## Host endpoints (effective)

Loopback binds (host):

- Jarvis backend health:
  - `http://127.0.0.1:18018/health`
- Jarvis backend (WS origin):
  - backend serves WebSocket at `/ws/live` (internal)
- Jarvis frontend:
  - `http://127.0.0.1:18080/jarvis/`

Public endpoints (via edge Caddy):

- Jarvis UI:
  - `https://assistance.idc1.surf-thailand.com/jarvis/`
- Jarvis WS:
  - `wss://assistance.idc1.surf-thailand.com/jarvis/ws/live`

Notes:

- Hitting a WS URL in a browser as HTTP GET often returns `404`; use a WS client.
- Public `/jarvis/ws/live` must reverse-proxy to backend `/ws/live` (strip `/jarvis`).

## Ports (host binds)

From `stacks/idc1-assistance/docker-compose.yml`:

- `127.0.0.1:18018` -> `jarvis-backend:8018`
- `127.0.0.1:18080` -> Jarvis frontend container
- `127.0.0.1:18030` -> `deep-research-worker:8030`
- `127.0.0.1:3051` -> `mcp-bundle:3050`

## Source-of-truth locations

- Compose:
  - `stacks/idc1-assistance/docker-compose.yml`
- Env templates:
  - `stacks/idc1-assistance/.env.example`
  - `stacks/idc1-assistance/.env.local` (developer convenience; do not commit secrets)
- Host edge proxy documentation:
  - `hosts/idc1/CONFIG.md`
- Assistance service docs:
  - `services/assistance/docs/CONFIG.md`

## Key environment variables (overview)

Backend:

- `GEMINI_API_KEY`
- `GEMINI_LIVE_MODEL`
- `WEAVIATE_URL` (default `http://weaviate:8080`)
- `MCP_BASE_URL` (default `http://mcp-bundle:3050`)
- `MCP_PLAYWRIGHT_BASE_URL`

Google Sheets SSoT for gems/memory/knowledge/notes:

- `CHABA_SS_SYS`
- `CHABA_SS_SYS_SH` / `CHABA_SS_SYS_SYS_SHEET`
- `CHABA_SS_SYS_MEMORY_SHEET`
- `CHABA_SS_SYS_KNOWLEDGE_SHEET`
- `CHABA_SS_SYS_NOTES_SHEET`

Frontend:

- `VITE_JARVIS_WS_URL`
  - should be `wss://assistance.idc1.surf-thailand.com/jarvis/ws/live`

## MCP (1MCP) configuration gotchas

- Child MCP servers do **not** automatically inherit all container environment.
- If a child server needs env vars, provide them via the 1MCP per-server config.
- If generating `mcp.json` via heredoc in compose, avoid `${VAR}` in the JSON content (compose may expand it at deploy-time). Prefer `$${VAR}`.

## Verification checklist (post-redeploy)

- Backend health:
  - `curl -fsS http://127.0.0.1:18018/health`
- WS path reachability (once TLS is correct):
  - use a WS client against `wss://assistance.idc1.surf-thailand.com/jarvis/ws/live`

## Deploy

Canonical flow on the Docker host:

- `./scripts/deploy-idc1-assistance.sh`

