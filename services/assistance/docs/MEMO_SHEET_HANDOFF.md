# Memo / Memory Sheet Handoff (Jarvis)

Operator SSOT:

- `services/assistance/docs/ACTION.md`

API SSOT:

- Prefer the live backend OpenAPI: `GET /openapi.json`

This doc is meant to be a quick handoff for another chat/session to safely work on Jarvis “memo/memory sheet” behavior without having to re-discover the conventions.

## What “memo sheet” means in this repo

Jarvis uses Google Sheets as the **authoritative store** for:

- **System KV** (feature flags / configuration)
- **Memory** (user/system facts Jarvis should remember)
- **Knowledge** (larger reference snippets; loaded separately)

The backend loads these into the live WebSocket session state and also caches them in `_SHEET_MEMORY_CACHE`.

## Where it lives (code)

File:

- `services/assistance/jarvis-backend/main.py`

Key functions:

- **Load system + memory/knowledge**: `_load_ws_sheet_memory(ws)`
- **Write system KV**: `_sys_kv_upsert_sheet(key=..., value=...)`
- **Write memory**: `_memory_sheet_upsert(ws, key=..., value=..., scope=..., priority=..., enabled=..., source=...)`

Tests:

- `services/assistance/jarvis-backend/test_sheet_upserts_timestamps.py`

## Required env vars

System Sheets:

- `CHABA_SYSTEM_SPREADSHEET_ID` (required)
- `CHABA_SYSTEM_SHEET_NAME` (required)

Notes:

- Memory/knowledge sheet names are discovered at runtime from the system sheet (the backend stores it into `ws.state.memory_sheet_name`, `ws.state.knowledge_sheet_name`).

## Sheet schema conventions

### KV5 columns (minimum)

Both Memory and Knowledge sheets follow the KV5 core:

- `key` (string)
- `value` (string)
- `enabled` (boolean-ish; the backend treats values like `true/false/1/0`)
- `scope` (string; usually `session|user|global`)
- `priority` (number)

### Timestamp columns (optional but supported)

If the sheet includes these headers, upsert logic uses them:

- `created_at`
- `updated_at`

Timestamp format expected/used by the upsert helpers:

- RFC3339 UTC with `Z` suffix, e.g. `2026-03-17T20:25:00Z`

### Extra columns

Sheets may contain additional columns (e.g. `source`, `notes`, etc.). The upsert logic is designed to **not clobber unrelated columns** when operating in header-aware mode.

## Header-aware upsert behavior (important)

### Why

Old code assumed fixed columns (e.g. `A:E`). This breaks when new columns are added (timestamps, notes, source) because updates can shift columns or overwrite data.

### Current rules (system KV + memory sheet)

Both `_sys_kv_upsert_sheet` and `_memory_sheet_upsert` do:

- Read a wider range (currently `A:Z`) to detect a header row.
- Build a case-insensitive header index mapping (`key`, `value`, `enabled`, etc.).

If a valid header is detected:

- **Update path** (key exists):
  - Preserve the existing `created_at` if present and non-empty.
  - Always set `updated_at = now` (RFC3339 UTC `Z`).
  - Only change known columns (key/value/enabled/scope/priority/source/timestamps) and keep other columns from the existing row.

- **Append path** (key not found):
  - Create a new row sized to the header length.
  - Set `created_at = now` (if that column exists).
  - Set `updated_at = now` (if that column exists).

If **no header** is detected:

- Fall back to legacy “fixed columns” behavior.
  - System KV fallback historically updated `A:E`.
  - Memory fallback historically updated the legacy core fields.

This fallback exists for backward compatibility with older sheets.

## How writes are triggered

### Deterministic UI writes (recommended)

Frontend can send a WS message (example):

```json
{"type":"memory","action":"add","key":"user.preference.language","value":"Thai","scope":"user","priority":10}
```

Backend handles this and calls `_memory_sheet_upsert(...)`.

### Model-initiated writes (Gemini tool calls)

Gemini Live can call a tool like `memory_add(...)`.

Feature gates live in system KV:

- `memory.write.enabled` (master switch)
- `memory.autowrite.enabled` (model-initiated writes)

## Memo append endpoint (Google Sheets)

Jarvis also supports a simpler “memo sheet” append flow intended for quick logging / handoff items.

This is distinct from the KV5 “Memory sheet” described above:

- Memo append is an HTTP endpoint that appends rows to a configured sheet.
- Memory writes are KV upserts (key/value/enabled/scope/priority) via WS messages or tool calls.

Endpoint:

- `POST /jarvis/memo/add` (alias: `POST /memo/add`)

Local (typical):

- `http://127.0.0.1:18018/jarvis/memo/add`

Public (when edge proxy routes `/jarvis/api/*` to backend):

- `https://assistance.idc1.surf-thailand.com/jarvis/api/jarvis/memo/add`

Requirements (system KV):

- `memo.enabled = TRUE`
- `memo.sheet_name = <sheet tab name>`
- Optional: `memo.spreadsheet_name` or `memo.spreadsheet_id`

Optional auth:

- If `jarvis.api_token` (sys_kv) or `JARVIS_API_TOKEN` (env) is set, requests must include header `X-Api-Token: <token>`.

JSON body (example):

- `memo` (required): string
- `group` (optional): string
- `subject` (optional): string
- `status` (optional): string (defaults to `new`)
- `v` (optional): string
- `result` (optional): string

Common error strings:

- `memo_disabled`
- `missing_memo_ss`
- `missing_memo_sheet_name`

## Testing guidance

### Unit tests for upsert invariants

Use `test_sheet_upserts_timestamps.py` as a template:

- Stub `google.genai` modules so importing `main.py` doesn’t require external deps.
- Mock `_mcp_tools_call` to return sheet read payloads and capture update/append requests.
- Assert:
  - `created_at` is preserved on update
  - `updated_at` is always valid RFC3339 UTC `Z`
  - unrelated columns remain unchanged

### What to test when changing sheet logic

- **Header present**: update + append
- **Header missing**: legacy fallback path
- **Partial headers**: missing `created_at`/`updated_at` should not crash

## Common failure modes / debugging

- **`missing_env: CHABA_SYSTEM_SPREADSHEET_ID`**
  - Backend can’t find the system spreadsheet. Ensure the env var is present in the running service.

- **`missing_memory_sheet_name`**
  - The backend didn’t discover the Memory sheet name. Usually means system sheet load failed.

- **Timestamps become invalid / blank**
  - Usually caused by fixed-column writes into a sheet that has added columns. Ensure header-aware mode is engaged.

## Minimal “do not break prod” rules

- Prefer **header-aware** edits; avoid hard-coding column letters.
- Preserve `created_at` on updates.
- Always set `updated_at` on writes.
- Do not overwrite unrelated columns.
- Keep fallback behavior for older sheets.

## Related docs

- `services/assistance/docs/MEMORY.md` (high-level memory model)
