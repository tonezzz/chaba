# idc1-webtop live config

This file documents **effective runtime configuration** for the `idc1-webtop` stack (Webtops router + control panel + session containers) on the Docker host.

Rules:

- No secrets in this file.
- Prefer documenting **actual bind ports/URLs** that operators use.
- Compose defaults do not override values configured in **Portainer stack env**.

## Host endpoints (effective)

- Webtops control panel (CP):
  - Local: `http://127.0.0.1:3005/`
  - Public: `https://webtops.idc1.surf-thailand.com/cp/`

- Webtops router (reverse proxy for sessions):
  - Local bind: `http://127.0.0.1:3001/`
  - Public base URL (sessions): `https://webtops.idc1.surf-thailand.com/webtop/`

Notes:

- The router may return `404` at `/` (no landing page). Operators should use the CP to create/start a session and then open the session URL.

## Ports (host binds)

- `127.0.0.1:3001` -> webtops router
- `127.0.0.1:3005` -> webtops control panel

## Source-of-truth locations

- Stack env template:
  - `stacks/idc1-webtop/.env`
- Build contexts:
  - Router: `mcp/webtops-router`
  - CP: `mcp/webtops-cp`

## Environment variables (non-secret overview)

These are configured via `stacks/idc1-webtop/.env` and/or Portainer stack env.

### Router

- `WEBTOPS_ROUTER_PORT`
  - default: `3001`
- `WEBTOPS_BASE_PATH`
  - default: `/webtop`
- `WEBTOPS_ROUTER_STATE_DIR`
  - default: `./data/webtops-router`

### Control panel (CP)

- `WEBTOPS_CP_PORT`
  - default: `3005`

### Session containers

- `WEBTOPS_PUBLIC_BASE_URL`
  - example: `https://webtops.idc1.surf-thailand.com/webtop/`
- `WEBTOPS_DOCKER_NETWORK`
  - example: `idc1-stack_idc1-stack-net`
- `WEBTOPS_SESSION_IMAGE`
  - example: `lscr.io/linuxserver/webtop:latest`
- `WEBTOPS_SESSION_INTERNAL_PORT`
  - example: `3000`
- `WEBTOPS_SESSION_MOUNT_PATH`
  - example: `/config`

## Storage

Host-side state directories (relative to `stacks/idc1-webtop/`):

- `./data/webtops-router`
- `./data/mcp-webtops/state`
- `./data/mcp-webtops/snapshots`

Named volumes (shared across sessions):

- `webtops_workspaces`
  - mounted at: `/workspaces`
- `webtops_windsurf_cache`
  - mounted at: `/windsurf-cache`

## Minimal operator test

1) Open CP:

- `https://webtops.idc1.surf-thailand.com/cp/`

2) Create/start a session.

3) Open the session URL provided by the CP (under `WEBTOPS_PUBLIC_BASE_URL`).

4) Inside the Webtop desktop, open the browser and visit `https://example.com`.
