# idc1-portainer live config

## Ports and endpoints

- **Portainer MCP bundle (1mcp HTTP/SSE + Streamable HTTP)**
  - Host bind: `0.0.0.0:3052`
  - MCP URL: `http://127.0.0.1:3052/mcp?app=windsurf`
  - Health: `http://127.0.0.1:3052/health`

## Windsurf integration

Windsurf should connect to the dedicated WebSocket gateway:

- **WebSocket URL**: `ws://127.0.0.1:18183/ws`

This gateway forwards MCP traffic to:

- `http://host.docker.internal:3052/mcp?app=windsurf`

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