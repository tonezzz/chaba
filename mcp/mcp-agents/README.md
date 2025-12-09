# mcp-agents

Model Context Protocol (MCP) server that surfaces the `/test/agents` observability surface through structured tools. It speaks to the existing multi-agent API (`sites/a1-idc1/api/agents`) so Claude Desktop—or any MCP-capable client—can inspect sessions, archives, and health without opening the UI.

## Features

- **Session explorer**: `fetch_sessions` returns the latest saved runs for a workspace/user id.
- **Archive lookup**: `fetch_archives` exposes archived sessions (summary, message counts, agents involved).
- **Lightweight observability**: `observability_probe` hits `/api/health` and optionally `/api/agents/registry` to confirm the stack is online before pointing people at `/test/agents/`.
- **Configurable targets**: Point the server at any agents API base (dev-host, PC2, localhost) via `AGENTS_API_BASE`.

## Getting started

```bash
cd mcp/mcp-agents
npm install
npm run start
```

Environment variables are loaded from the repo-level `.env` (via `dotenv`) plus anything you export before launch. Useful overrides:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8046` | HTTP port to bind. |
| `AGENTS_API_BASE` | `http://127.0.0.1:4060/api` | Base URL for the multi-agent API (dev-host proxy, local PM2 service, etc.). |
| `AGENTS_DEFAULT_USER` | `default` | Workspace/user id used when a tool call omits `user_id`. |
| `AGENTS_DEFAULT_LIMIT` | `12` | Default number of sessions returned by `fetch_sessions`. |

## Data storage

Session JSON files now live inside this MCP package so everything remains co-located:

- Default path: `mcp/mcp-agents/data/agents/users`
- Override by exporting `AGENTS_DATA_ROOT` (the agents API and this MCP server will both honor it)

If you still have legacy files under `sites/a1-idc1/data/agents/users`, copy them into the new directory before restarting services.

The server exposes:

- `GET /health` – Confirms it can reach `${AGENTS_API_BASE}/../api/health`.
- `POST /invoke` – Standard MCP tool execution endpoint.
- `GET /.well-known/mcp.json` – Metadata used by MCP clients (declares the three tools above).

## Recommended workflow

1. Use `mcp-devops` workflow `preview-agents` to boot PM2 + dev-host proxies for `/test/agents`.  
2. Point `AGENTS_API_BASE` at the resulting API (usually `http://127.0.0.1:4060/api` when running locally or `https://dev-host.pc1:3100/test/agents/api` when tunneling).  
3. Register `mcp-agents` with MCP0 (or your MCP client) so downstream agents can query sessions/archives/health.  
4. Keep an eye on `c:\chaba\sites\a1-idc1\test\agents` for SPA updates; the backend already serves `/www/test/agents` if the built assets exist.

## Next steps

- Expand tool coverage (e.g., trigger new runs, pin sessions, upload attachments).  
- Wire the observability panel UI to highlight MCP results from this provider.  
- Document how to publish the SPA bundle alongside the API so `/test/agents` is always fresh.
