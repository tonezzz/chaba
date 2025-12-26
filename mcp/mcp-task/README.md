# mcp-task

A minimal MCP task orchestrator service.

## What it does (MVP)

- Provides an MCP-compatible HTTP API and SSE session endpoints.
- Persists tasks/runs to SQLite.
- Supports creating a task that will call a tool on another MCP HTTP provider when approved.

## Environment

- `PORT` (default `8016`)
- `MCP_TASK_DB_PATH` (default `/data/sqlite/mcp-task.sqlite`)
- `MCP_TASK_SERVERS` JSON array mapping server name to base URL.

Example:

```json
[
  {"name": "mcp-devops", "url": "http://mcp-devops:8012"}
]
```

## Endpoints

- `GET /health`
- `GET /tools`
- `POST /mcp`
- `POST /invoke`
- `GET /sse`
- `POST /messages?session_id=...`

## Tools

- `create_task`
- `approve_task`
- `get_task`
- `get_task_report`
- `list_tasks`
- `list_runs`

