# Docker management (default)

## Overview
Use `mcp-docker` as the default interface to manage Docker containers and Compose stacks.

It is an HTTP wrapper around Docker MCP tools and is designed to be discoverable by `mcp0` via `MCP0_PROVIDERS`.

## pc1-stack
### Service
- `mcp-docker` service name: `mcp-docker`
- Container: `pc1-mcp-docker`
- Default port: `8340`

### Local URLs
- Health: `http://127.0.0.1:8340/health`
- Tools: `http://127.0.0.1:8340/tools`
- MCP manifest: `http://127.0.0.1:8340/.well-known/mcp.json`
- Invoke: `POST http://127.0.0.1:8340/invoke`

### Tool invocation (HTTP)
List tools:
- `GET /tools`

Invoke a tool:
- `POST /invoke`

Request body format:
```json
{
  "tool": "list-containers",
  "arguments": {}
}
```

Examples:
- List containers:
```json
{
  "tool": "list-containers",
  "arguments": {}
}
```

- Get logs:
```json
{
  "tool": "get-logs",
  "arguments": { "container_name": "pc1-caddy" }
}
```

- Deploy a compose stack:
```json
{
  "tool": "deploy-compose",
  "arguments": {
    "project_name": "example",
    "compose_yaml": "services:\n  hello:\n    image: nginxdemos/hello\n    ports:\n      - '8088:80'\n"
  }
}
```

## idc1-stack
### Service
- `mcp-docker` service name: `mcp-docker`
- Default port: `8340`

### Env vars
In `stacks/idc1-stack/.env`:
- `MCP_DOCKER_BUILD_CONTEXT=../../mcp/mcp-docker`
- `MCP_DOCKER_PORT=8340`

### mcp0 provider registration
`stacks/idc1-stack/.env.example` registers `mcp-docker` in `MCP0_PROVIDERS`:
- `mcp-docker:http://mcp-docker:${MCP_DOCKER_PORT}|health=/health|capabilities=/.well-known/mcp.json`

### Bring up
On the idc1 host:
- Copy `stacks/idc1-stack/.env.example` to `stacks/idc1-stack/.env`
- Start the stack with your usual idc1 deploy method (e.g. `scripts/idc1-stack.ps1 up`)

## Integration with mcp0
`pc1-stack/.env.example` registers `mcp-docker` in `MCP0_PROVIDERS` so `mcp0` can discover it.

## pc1-stack (optional): MCP endpoint via mcp0 + Caddy
`pc1-stack` can expose an MCP-compatible endpoint on `mcp0.pc1.vpn` via Caddy.

Routes:
- `/.well-known/mcp.json` -> proxied to `pc1-mcp0:8351`
- `/mcp/messages*` -> proxied to `pc1-mcp0:8351` (supports streaming)
- `/mcp/tools/*` -> proxied to `pc1-mcp0:8351` (Docker tool endpoints)

Compatibility note:
- Some proxies/clients expect `/messages` instead of `/mcp/messages`. `mcp0` provides a `/messages` alias, and the pc1 Caddy routes rewrite `/mcp/messages` to `/messages` upstream.

If you modify ports, keep these aligned:
- `MCP_DOCKER_PORT`
- `MCP0_PROVIDERS` entry for `mcp-docker`

## Notes / safety
`mcp-docker` mounts the host Docker socket. Treat it as privileged:
- restrict exposure (prefer internal network access when possible)
- avoid running it on untrusted networks
