# MCP Tools Inventory

This document tracks the MCP servers used by the chaba lab and how to maintain them.

## Server Inventory

| Server | Type | Command | Purpose | Secrets / Env |
| --- | --- | --- | --- | --- |
| `yomi` | stdio | `/usr/bin/node /home/tony/.yomi/mcpb/run.mjs` | LINE conversation viewer | Basic-auth on web side |
| `github` | stdio (wrapper) | `/bin/bash /home/tony/CascadeProjects/chaba/.windsurf/run-github-mcp.sh` | GitHub MCP server | `~/.config/secrets/github-mcp.env` |
| `mcp-llama` | stdio (wrapper) | `/bin/bash /home/tony/CascadeProjects/chaba/.windsurf/run-llama-mcp.sh` | Local LLM endpoint | `LLAMA_URL` |
| `playwright` | stdio | `/usr/bin/npx -y @playwright/mcp@0.0.78` | Browser automation | None |
| `playwright` | HTTP/SSE | `http://localhost:8931/mcp` | Browser automation (long-running) | `~/.windsurf/run-playwright-mcp-http.sh` |

## Config Files

- **Global Windsurf config** (active): `~/.codeium/windsurf/mcp_config.json`
- **Project source of truth** (versioned): `chaba/.windsurf/mcp_config.json`
- **HTTP variant** (for long-lived browser sessions): `chaba/.windsurf/mcp_config.http.json`
- **Wrapper scripts**: `chaba/.windsurf/run-github-mcp.sh`, `chaba/.windsurf/run-llama-mcp.sh`, `chaba/.windsurf/run-playwright-mcp-http.sh`

## Initial Setup

1. Copy the project config into Windsurf:
   ```bash
   cp /home/tony/CascadeProjects/chaba/.windsurf/mcp_config.json ~/.codeium/windsurf/mcp_config.json
   ```
2. Ensure `~/.config/secrets/github-mcp.env` exports `GITHUB_PERSONAL_ACCESS_TOKEN`.
3. Ensure `LLAMA_URL` is exported in the MCP config `env` or in `~/.config/secrets/llama.env`.
4. Reload Windsurf/Cascade.

## Updating Versions

- **Playwright MCP**: find the latest version with `npm view @playwright/mcp version`, then update both `mcp_config.json` and `mcp_config.http.json` (and `run-playwright-mcp-http.sh`) to use the pinned version.
- **GitHub MCP server**: update the image tag in `run-github-mcp.sh` if you ever move off `latest`.

## HTTP Transport for Playwright

For headed or long-running browser work, start the Playwright MCP server on a fixed port:

```bash
nohup /home/tony/CascadeProjects/chaba/.windsurf/run-playwright-mcp-http.sh > /tmp/playwright-mcp.log 2>&1 &
```

Then switch the Windsurf MCP config to `mcp_config.http.json` and reload the IDE. The `playwright` server will use `url` instead of spawning a new process each time.

## Troubleshooting

- `GITHUB_PERSONAL_ACCESS_TOKEN not set` — the `github` wrapper could not find the secrets file or the env var.
- `LLAMA_URL not set` — the `mcp-llama` wrapper has no target URL.
- New MCP servers not appearing — reload or restart Windsurf/Cascade after editing `mcp_config.json`.
