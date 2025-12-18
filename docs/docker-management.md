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

## Integration with mcp0
`pc1-stack/.env.example` registers `mcp-docker` in `MCP0_PROVIDERS` so `mcp0` can discover it.

If you modify ports, keep these aligned:
- `MCP_DOCKER_PORT`
- `MCP0_PROVIDERS` entry for `mcp-docker`

## Notes / safety
`mcp-docker` mounts the host Docker socket. Treat it as privileged:
- restrict exposure (prefer internal network access when possible)
- avoid running it on untrusted networks
