# idc1-stack

## Overview
This stack runs MCP services on the **idc1 host**.

This branch adds `1mcp-agent` (aggregated MCP) on port `3050` (bound to `127.0.0.1` on the host).

## 1mcp URLs
- VPN (no auth): `https://1mcp.idc1.vpn/mcp?app=windsurf`
- Public (basic auth): `https://1mcp.idc1.surf-thailand.com/mcp?app=windsurf`

## Start / Restart
From your workstation:
- `pwsh ./scripts/idc1-stack.ps1 -Action up -Profile mcp-suite`

## Verify
- Health:
  - `https://1mcp.idc1.vpn/health`
  - `https://1mcp.idc1.surf-thailand.com/health`

- Smoke test (VPN):
  - `pwsh ./scripts/idc1-1mcp-smoke-test.ps1 -BaseUrl https://1mcp.idc1.vpn`

- Smoke test (public, requires auth):
  - `pwsh ./scripts/idc1-1mcp-smoke-test.ps1 -BaseUrl https://1mcp.idc1.surf-thailand.com -Username chaba -Password '<your_password>'`

## Public auth (Caddy)
The public hostname uses Caddy `basicauth` and requires a bcrypt hash.

Update `sites/idc1/config/Caddyfile` and replace `__REPLACE_ME_BCRYPT__` with a hash.

Generate a bcrypt hash (example):
- `docker run --rm caddy:2-alpine caddy hash-password --algorithm bcrypt --plaintext "<password>"`

## VPN hostname support
To wire up `1mcp.idc1.vpn` on the idc1 host (CoreDNS + VPN Caddyfile), run:
- `./scripts/idc1-fix-1mcp-vpn.sh`

This script expects `SSH_USER`, `SSH_HOST`, `SSH_KEY_PATH` (and optionally `SSH_PORT`).

## Config files
- `stacks/idc1-stack/docker-compose.yml` (adds `1mcp-agent`)
- `stacks/idc1-stack/1mcp.json` (backends aggregated by 1mcp)
- `sites/idc1/config/Caddyfile` (public route)
