# mcp-nodehost (planned)

This repository is migrating the app-demo builder/orchestrator service name from `mcp-apphost` to `mcp-nodehost`.

## Current state

- The `pc1-stack` compose does not currently reference `mcp-apphost`/`mcp-nodehost`.
- The `stacks/app-demo` folder currently contains only `.env.example`, `README.md`, and an `outputFormat` log. The stack compose and Caddy config files are not present at this time.
- The service source folder `mcp/mcp-apphost` (and `mcp/mcp-nodehost`) is not present in `c:\chaba\mcp` at this time.

## Intended layout (when restored)

- Service code:
  - `mcp/mcp-nodehost/` (renamed from `mcp/mcp-apphost/`)
- app-demo stack:
  - `stacks/app-demo/docker-compose.yml`
  - `stacks/app-demo/Caddyfile` (ingress)
  - `stacks/app-demo/app-host.Caddyfile` (static host)
  - `stacks/app-demo/.env.example`

## Naming rules

- Service/container name should be `mcp-nodehost`.
- URLs and upstreams should target `mcp-nodehost` (e.g. `reverse_proxy mcp-nodehost:8080`).
- Keep existing `APPHOST_*` environment variable names for compatibility unless a separate migration is performed.

## Resume checklist

- Restore/create the missing app-demo compose + Caddy files.
- Restore/create the service folder under `mcp/mcp-nodehost`.
- Search and replace:
  - `mcp-apphost` -> `mcp-nodehost`
  - `mcp/mcp-apphost` -> `mcp/mcp-nodehost`
- Rebuild and smoke test:
  - `GET /api/health`
  - `GET /api/status`
  - `POST /api/publish` (with token header if enabled)
