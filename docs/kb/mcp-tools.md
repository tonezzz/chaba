# MCP Tools Inventory

This document tracks the MCP servers used by the chaba lab and how to maintain them.

## Server Inventory

| Server | Type | Command | Purpose | Secrets / Env |
| --- | --- | --- | --- | --- |
| `yomi` | stdio | `/usr/bin/node /home/tony/.yomi/mcpb/run.mjs` | LINE conversation viewer | Basic-auth on web side |
| `github` | stdio (wrapper) | `/bin/bash /home/tony/CascadeProjects/chaba/.windsurf/run-github-mcp.sh` | GitHub MCP server | `~/.config/secrets/github-mcp.env` |
| `mcp-llama` | stdio (wrapper) | `/bin/bash /home/tony/CascadeProjects/chaba/.windsurf/run-llama-mcp.sh` | Local LLM endpoint | `LLAMA_URL` |
| `mddb` | HTTP | `http://localhost:9001` | Multi-Document Database (semantic search) | Docker container `mddb` |
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
- MDDB 404 errors — MDDB requires MCP JSON-RPC POST format, not simple HTTP GET. Use `POST /tools/call` with JSON payload.

## MDDB Usage

MDDB provides semantic search and document storage with Ollama embeddings (nomic-embed-text, 768 dimensions).

**Key endpoints**:
- MCP API: `http://localhost:9001` (JSON-RPC via `/tools/call`)
- HTTP API: `http://localhost:11023`
- Web panel: `http://localhost:3002`

**Available tools**:
- `add_document` - Add/update documents with metadata
- `search_documents` - BM25 + metadata filtering search
- `semantic_search` - Vector similarity search (requires embeddings)
- `delete_document` - Remove documents
- `get_stats` - Server statistics and collection info
- `aggregate` - Metadata facets and date histograms

**Example usage**:
```python
# Get server stats
mcp_call_tool("mddb", "get_stats", {})

# Search with filters
mcp_call_tool("mddb", "search_documents", {
  "collection": "yomi-personal",
  "filter_meta": {"unread_count": [">", "10"]},
  "limit": 5
})

# Semantic search
mcp_call_tool("mddb", "semantic_search", {
  "query": "meeting schedule",
  "collection": "yomi-work"
})
```

**Collections**: Organized by topic (kb-system, kb-features, yomi-personal, etc.)
