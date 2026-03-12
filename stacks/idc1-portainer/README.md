This file contains info about idc1-portainer stack.
Live config info is in docs/CONFIG.md

## Portainer MCP

This stack runs a local Portainer instance plus a `portainer-mcp` server via `mcp-bundle`.

### How Windsurf connects

- **Portainer MCP (HTTP)**: `http://127.0.0.1:3052/mcp?app=windsurf`
- **Portainer MCP (WebSocket gateway)**: `ws://127.0.0.1:18183/ws`

### Redeploying a stack via Portainer MCP

There are two common approaches:

#### Stop/Start redeploy

Use this when:
- You want a fast restart of the stack using the *existing* compose file stored in Portainer.
- You are not changing the stack definition in Portainer (only want containers restarted).

Tools:
- `portainer_1mcp_stopLocalStack`
- `portainer_1mcp_startLocalStack`

Effect:
- Stops then starts the stack.
- Typically recreates containers and restarts services.
- Does **not** change the compose content.

#### updateLocalStack redeploy

Use this when:
- You want to *change* the stack definition in Portainer (compose content / env vars).
- You want to re-apply the stack file (often used as a “redeploy with updated spec”).

Tools:
- `portainer_1mcp_getLocalStackFile`
- `portainer_1mcp_updateLocalStack`

Effect:
- Updates Portainer’s stored stack file, then redeploys from the updated content.

### Note about write operations

Portainer MCP can be run in read-only mode.
If you don’t see `start/stop/update` tools in `tools/list`, set `PORTAINER_READ_ONLY=0` in `stacks/idc1-portainer/.env` and recreate the `mcp-bundle` container.