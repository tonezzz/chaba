# MCP Servers (Architecture)

## What it is
A containerized collection of MCP servers (one subfolder per server).

## Folder naming
- `mcp-servers/<server-name>/`

## Persistence
- Each MCP server should declare its own named volume(s) or bind mount(s) for caches/state.

## Networking
- Default: internal-only.
- Public exposure must be explicit and documented.
