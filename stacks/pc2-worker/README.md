# pc2-worker

## Overview
This stack runs the PC2 worker services.

Key components:
- `1mcp-agent` (aggregates MCP backends)
- `mcp-glama` (Glama MCP provider via Streamable HTTP)
- Supporting MCP servers (filesystem, docker, fetch, github, vaja)

## Start
From `stacks/pc2-worker/`:

- `docker compose --profile mcp-suite up -d --build 1mcp-agent`

## Verify
- OAuth/status dashboard:
  - `http://127.0.0.1:3050/oauth`

Note: the agent starts in a synchronous loading mode and may take ~30-90s on first boot while `docker-mcp` initializes.

## Windsurf (team "official" MCP URL)
Update your Windsurf MCP config:

- `C:\Users\Admin\.codeium\windsurf\mcp_config.json`
  - **Default (pc1)**: `url: http://1mcp.pc1.vpn:3051/mcp?app=windsurf`
  - **Alternative (pc2)**: `url: http://1mcp.pc2.vpn:3050/mcp?app=windsurf`

Note: for VPN usage, this endpoint is currently HTTP-only (do not use HTTPS).

## Secret Management Workflow (pc2-worker)
1. **Authoritative template**: `stacks/pc2-worker/.env.example` stays in git with `__REPLACE_ME__` placeholders.
2. **Private overrides**: create an untracked file such as `stacks/pc2-worker/.env.local` or a secrets bundle (`.secrets/.env/tony.env`) containing real values (MCP0 admin token, API keys, etc.).
3. **Sync helper**: run `pwsh ./scripts/pc2-worker/sync-env.ps1 -SourcePath <path-to-private-env>` before invoking any compose workflow.
4. **Automations**: for remote ops, prefer `scripts/pc2-worker/pc2-stack.ps1` (sync + up/down/status via WSL+SSH).

## Notes
- `1mcp-agent` config lives in `stacks/pc2-worker/1mcp.json`.
- Glama is configured as `glama` (HTTP/Streamable) in `1mcp.json`.
