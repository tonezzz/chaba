# pc1-stack

## Overview
This stack provides a VPN-only chat UI (OpenChat UI) backed by an OpenAI-compatible gateway service. The gateway uses Glama as the model backend and exposes MCP tools from `1mcp-agent` (including `mcp-task`, `mcp-devops`, and `docker`) for tool calling.

## Services (key)
- `openchat-ui` (Next.js): user-facing chat UI
- `mcp-openai-gateway` (FastAPI): OpenAI-compatible `/v1/*` endpoints used by OpenChat UI
- `1mcp-agent`: MCP tool aggregator (HTTP Streamable)
- `mcp-task`: task/run service (exposed as tools via 1mcp)
- `mcp-devops`: devops workflows (tools via 1mcp)

## Start
From `stacks/pc1-stack/`:

```powershell
# Copy env template and set secrets
copy .env.example .env

# Start the stack
Docker compose --profile mcp-suite up -d --build
```

## URLs
### Direct ports
- OpenChat UI: `http://pc1.vpn:3170`
- 1mcp-agent: `http://1mcp.pc1.vpn:3051/health`
- OpenAI gateway: `http://pc1.vpn:8181/health`

### VPN HTTPS (stack Caddy)
pc1-stack runs a Caddy container using `tls internal` on host port `3443`.

- OpenChat UI: `https://pc1.vpn:3443/chat/`
- OpenAI gateway (health): `https://pc1.vpn:3443/openai/health`
- OpenAI gateway (models): `https://pc1.vpn:3443/openai/v1/models`
- 1mcp-agent: `https://pc1.vpn:3443/1mcp/health`

## Notes
- `stacks/pc1-stack/.env` is local-only (gitignored). Do not commit real API keys.
- `OPENAI_GATEWAY_DEBUG=1` enables `/debug/*` endpoints on the gateway for troubleshooting.
