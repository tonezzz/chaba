# Jarvis System Sheets

This document describes how Jarvis loads the **system sheet** and how `system reload` works end-to-end.

## Environment variables

Jarvis requires these environment variables:

- `CHABA_SYSTEM_SPREADSHEET_ID`
- `CHABA_SYSTEM_SHEET_NAME`

## System KV keys

### `system.sheets` (required)

`system.sheets` is a comma-separated list of sheet spec tokens.

Supported forms:

- `memory,knowledge`
- `memory:<TAB_NAME>,knowledge:<TAB_NAME>`

Notes:

- Tokens are **not** `key=value` pairs. `=` is invalid.
- The loader expects to find both `memory` and `knowledge` entries.

### Per-sheet metadata (optional)

For each sheet role (`memory`, `knowledge`) you can provide:

- `<sheet>.info`
- `<sheet>.instruction`

Examples:

- `memory.info=System memory for internal usage.`
- `memory.instruction=Prefer memory items when answering user-specific questions.`
- `knowledge.info=Internal knowledge base.`
- `knowledge.instruction=Use knowledge items as canonical definitions and policies.`

## Backend reload flow (diagram)

```mermaid
sequenceDiagram
  autonumber
  participant FE as Frontend (Jarvis UI)
  participant BE as jarvis-backend
  participant MCP as mcp-google-sheets

  FE->>BE: WS {"type":"system","action":"reload","mode":"full"}
  BE-->>FE: text: reloading system

  BE->>BE: clear caches
  BE->>BE: _load_ws_sheet_memory()
  BE->>MCP: google_sheets_values_get(range="<system_sheet>!A:E")
  MCP-->>BE: rows (system KV)

  BE->>BE: parse sys_kv
  BE->>BE: read system.instruction (optional)
  BE->>BE: read system.sheets (required)
  BE->>BE: read memory.info / memory.instruction (optional)
  BE->>BE: read knowledge.info / knowledge.instruction (optional)

  BE->>MCP: google_sheets_values_get(range="<knowledge_sheet>!A:E")
  MCP-->>BE: rows (knowledge KV)

  BE->>MCP: google_sheets_values_get(range="<memory_sheet>!A:E")
  MCP-->>BE: rows (memory KV)

  BE->>BE: build memory_context_text / knowledge_context_text
  BE-->>FE: text: system reloaded | memory=N knowledge=M

  Note over BE: If system.sheets is missing/invalid or any sheet read fails
  BE-->>FE: error(kind=reload_system_failed, detail=...)
```

### Explanation

- Jarvis treats the **system sheet** as authoritative configuration.
- `system.sheets` controls which sheet tabs are loaded after the system KV is loaded.
- Jarvis does **not** silently fall back to defaults; missing config is reported as an error to make debugging easier.

## Startup prewarm + client connect status

### Startup prewarm

When `jarvis-backend` starts (even if no UI is connected), it runs a background prewarm job:

- Loads system KV from the system sheet
- Reads `system.sheets`
- Loads memory + knowledge sheets
- Populates in-process caches

If no UI is connected, no WebSocket messages are emitted. The result is only visible in backend logs.

### Client connect status

When a client connects to `/ws/live`, the backend sends short status lines:

- A cache-based sheet summary (memory/knowledge sheet names + counts)
- A startup prewarm summary:
  - `Startup prewarm: ok | memory=X knowledge=Y`
  - or `Startup prewarm: error | <reason>`

Note: sheets are still not auto-loaded into the current chat session beyond cache application; use `system reload` to force a full reload and to see explicit reload errors.

## System sheet reload (diagram)

```mermaid
flowchart TD
  A[system reload] --> B[Load system KV sheet]
  B --> C{system.sheets present?}
  C -- no --> E[Error: missing_system_sheets]
  C -- yes --> D[Load each sheet in system.sheets]
  D --> F[knowledge sheet -> ws.state.knowledge_items]
  D --> G[memory sheet -> ws.state.memory_items]
  B --> H[system.instruction -> ws.state.system_instruction_extra]
  F --> I[Build knowledge_context_text]
  G --> J[Build memory_context_text]
  I --> K[Reload complete]
  J --> K
```

### Explanation

- `system.instruction` is optional and is injected into Gemini system prompts (Live and non-Live) as extra guidance.
- `<sheet>.info` is optional and is included near the top of the corresponding context block.
- `<sheet>.instruction` is optional and is injected into Gemini system prompts as extra guidance about how to use that sheet.
- `system.sheets` is required and must include entries for both `memory` and `knowledge`.
- Each sheet loaded via `_load_sheet_kv5` expects columns: `key,value,enabled,scope,priority`.