---
category: operations
---

# MDDB Claude Bridge Spec

## Purpose
Enable Claude Desktop to use the local MDDB MCP server through a stdio bridge. Claude Desktop only supports MCP 2024-11-05 over stdio, while MDDB exposes streamable HTTP with MCP 2025-11-25 and advertises 70+ tools that overload Claude's tool list.

## Components
- `docker tradik/mddb:latest` container, MCP endpoint published to `http://localhost:9001/mcp`
- `/home/tony/.config/Claude/mddb-bridge.py` — stdio-to-HTTP bridge and tool filter
- `/home/tony/.config/Claude/mcp-proxy-lenient.py` — `mcp-proxy` wrapper that disables output-schema validation
- `~/.config/Claude/claude_desktop_config.json` `mcpServers` entry

## Claude Desktop `mcpServers` configuration
```json
{
  "mcpServers": {
    "mddb": {
      "command": "/usr/bin/python3",
      "args": ["/home/tony/.config/Claude/mddb-bridge.py"]
    }
  }
}
```

## Allowed tools
The bridge exposes only these six core MDDB tools to Claude:
- `add_document`
- `search_documents`
- `delete_document`
- `get_stats`
- `aggregate`
- `semantic_search`

## How it works
1. Claude Desktop launches `mddb-bridge.py` as a stdio process.
2. `mddb-bridge.py` runs `mcp-proxy-lenient.py` against `http://localhost:9001/mcp`.
3. `mcp-proxy-lenient.py` patches `mcp.client.session.ClientSession._validate_tool_result` to skip validation, so MDDB tools that return plain text JSON instead of MCP `structuredContent` are accepted.
4. `mddb-bridge.py` filters the `tools/list` response to the allowed tool names and strips 2025-only fields such as `outputSchema` and `annotations` from each tool.

## Verification
```bash
curl -s http://localhost:9001/mcp
# {"error":"MCP-Session-Id required"}
```
A test `get_stats` call through the bridge returns live collection statistics.

Always fully restart Claude Desktop after modifying the bridge.

## Optional HTTPS endpoint
A local `mkcert` + Caddy reverse proxy on `https://tony-omen.local:9443/mcp` was created during exploration. It is not used by Claude Desktop's connector because the connector cannot handle MDDB's MCP 2025 protocol. The stdio bridge remains the supported integration for Claude Desktop.
