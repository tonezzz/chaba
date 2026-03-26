# TOOLS.md — WebSocket / Tools Protocol Notes

→ Back to [ACTION.md](ACTION.md)

---

## Overview {#overview}

The MCP (Model Context Protocol) stack exposes tools to AI assistants via a WebSocket-based aggregation layer (`1mcp-agent`). This doc covers the protocol conventions and known quirks.

---

## MCP tool aggregation {#mcp-aggregation}

- **`1mcp-agent`** (port 3051 on PC1) is the single MCP entrypoint for clients.
- It aggregates tools from downstream MCP services registered in `stacks/pc1-stack/1mcp.json`.
- Clients connect to `1mcp-agent` and see a unified tool list.

### Registering a new tool/service

1. Add the service to the relevant stack compose file.
2. Register the service endpoint in `stacks/pc1-stack/1mcp.json`.
3. Restart `pc1-stack` (`docker compose up -d --no-deps 1mcp-agent`).

---

## Known tools {#known-tools}

| Tool service | Port | Tools exposed |
|-------------|------|--------------|
| `mcp-coding-agent` | 8350 | `analyze_code`, `fix_bugs`, `review_code` |
| `mcp-devops` | (see `pc1-devops.json`) | DevOps automation tools |
| `mcp-agents` | (see `pc1-stack.json`) | Agent management |
| `mcp-rag` | (see `pc1-stack.json`) | RAG / document search |
| `mcp-playwright` | (see `pc1-stack.json`) | Browser automation |
| `mcp-docker` | (see `pc1-stack.json`) | Docker management |
| `mcp-tester` | 8335 | Test runner (mcp-suite profile) |
| `mcp-task` | (see `pc1-stack.json`) | Task management |

---

## WebSocket protocol notes {#ws-protocol}

- MCP clients communicate with `1mcp-agent` over WebSocket (WS) or Server-Sent Events (SSE), depending on the client.
- The aggregator forwards tool calls to the appropriate downstream service and returns the result.
- If a downstream service is unreachable, `1mcp-agent` will return an error for tools registered to that service; other tools remain available.

---

## dev-host gateway routes {#dev-host-routes}

`dev-host` (port 3100) also acts as an HTTP gateway with the following routes:

| Path | Source | Notes |
|------|--------|-------|
| `/a1-idc1/*` | `sites/a1-idc1` | Static + SPA fallback |
| `/idc1/*` | `sites/idc1` | Static + SPA fallback |
| `/test/chat/*` | `sites/a1-idc1/test/chat` | SPA fallback |
| `/test/agents/api` | Agents backend | Used by `AGENTS_API_BASE` |
| `/api/deploy/*` | Deploy endpoints | Requires `DEV_HOST_PUBLISH_TOKEN` |

See [`docs/dev-host.md`](../../../docs/dev-host.md) for full reference.

---

## Reference

- [SYSTEM.md](SYSTEM.md) — architecture + key services
- [CONFIG.md](CONFIG.md) — ports + endpoints
- [`docs/stacks.md`](../../../docs/stacks.md) — stack index
