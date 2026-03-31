# idc1-portainer live config

## Ports and endpoints

- **Portainer UI + HTTP API (Community Edition on this host)**
  - API base: `http://127.0.0.1:9000`
  - Status: `http://127.0.0.1:9000/api/status`
  - Stacks: `http://127.0.0.1:9000/api/stacks`

- **Portainer MCP bundle (1mcp HTTP/SSE + Streamable HTTP)**
  - Host bind: `0.0.0.0:3052`
  - MCP URL: `http://127.0.0.1:3052/mcp?app=windsurf`
  - Health: `http://127.0.0.1:3052/health`

## Windsurf integration

Windsurf should connect to the dedicated WebSocket gateway:

- **WebSocket URL**: `ws://127.0.0.1:18183/ws`

This gateway forwards MCP traffic to:

- `http://host.docker.internal:3052/mcp?app=windsurf`

## Deploy script configuration (idc1-assistance)

The host-side deploy script `scripts/deploy-idc1-assistance.sh` triggers a Portainer-authoritative redeploy via the Portainer HTTP API (CE compatible).

Set these on the Docker host (do not commit):

```bash
export PORTAINER_URL='http://127.0.0.1:9000'
export PORTAINER_API_KEY='ptr_...'
export PORTAINER_ENDPOINT_ID='2'
export PORTAINER_STACK_NAMES='idc1-assistance-infra,idc1-assistance-mcp,idc1-assistance-core,idc1-assistance-workers'
export COMPOSE_FILES='stacks/idc1-assistance-infra/docker-compose.yml,stacks/idc1-assistance-mcp/docker-compose.yml,stacks/idc1-assistance-core/docker-compose.yml,stacks/idc1-assistance-workers/docker-compose.yml'
export HEALTHCHECK_URL='http://127.0.0.1:18018/health'
export HEALTHCHECK_CONTAINER_NAME='idc1-assistance-core-jarvis-backend-1'
```

Notes:

- The script also accepts `PORTAINER_TOKEN` as an alias for `PORTAINER_API_KEY`.
- If `PORTAINER_API_KEY`/`PORTAINER_TOKEN` is not set in the shell, the script will attempt to source `stacks/idc1-portainer/.env` (local-only).

## Environment variables

This stack reads its Portainer MCP settings from:

- `stacks/idc1-portainer/.env`

Key variables:

- `PORTAINER_SERVER`
  - Example: `portainer:9443`
- `PORTAINER_TOKEN`
  - Portainer admin API token.
- `PORTAINER_DISABLE_VERSION_CHECK`
  - Set to `1` to allow `portainer-mcp` to run against newer Portainer versions.
- `PORTAINER_READ_ONLY`
  - `1` = only list/get tools
  - `0` = enable write tools (start/stop/update stack)

## Enabling stack redeploy tools

To enable `portainer_1mcp_startLocalStack` / `portainer_1mcp_stopLocalStack` / `portainer_1mcp_updateLocalStack`:

1) Set `PORTAINER_READ_ONLY=0` in `stacks/idc1-portainer/.env`
2) Recreate the bundle:

```bash
docker compose -f stacks/idc1-portainer/docker-compose.yml up -d --force-recreate mcp-bundle
```

## Redeploying a stack via Portainer MCP

- **Stop/Start**
  - `portainer_1mcp_stopLocalStack`
  - `portainer_1mcp_startLocalStack`

- **Update**
  - `portainer_1mcp_getLocalStackFile`
  - `portainer_1mcp_updateLocalStack`

## Common gotchas

- `:9443` might not be reachable from the host even if Portainer is configured internally as `portainer:9443`.
- MCP bundle endpoint (`:3052`) is not the same thing as the Portainer HTTP API endpoint (`:9000`).
- Git-backed stack redeploy is not reliably available via the Portainer HTTP API on this host (`/api/stacks/{id}/git/redeploy` returned `405`/`400` in testing). Prefer Portainer UI redeploy for Git-backed stacks, or use Portainer MCP stack update tools when appropriate.