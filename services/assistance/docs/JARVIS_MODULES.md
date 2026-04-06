# Jarvis backend modules

## jarvis/memo_sheet.py

Purpose:
Ensure the memo Google Sheet tab has the expected header schema and that legacy/duplicate headers are normalized.

Key entrypoint:
- `jarvis.memo_sheet.ensure_header(...)` (async)

Inputs/outputs:
- Inputs:
  - `spreadsheet_id`, `sheet_a1`, `force`
  - Injected deps: `sheet_get_header_row`, `mcp_tools_call`, `pick_sheets_tool_name`, `mcp_text_json`
- Output: `None` (raises on failure)

Dependencies / injection points:


Invariants / safety notes:
- Header reads/writes are capped to the known schema width.
- Best-effort clearing of trailing header cells to avoid “ghost” legacy columns.
- Best-effort checkbox validation for `active`; skipped if MCP server lacks batchUpdate.

Smoke test:

(removed)


## jarvis/sheets_utils.py

Purpose:
Small Sheets helpers used by memo + other sheet-backed features.

Key entrypoints:
- `jarvis.sheets_utils.sheet_name_to_a1(...)`
- `jarvis.sheets_utils.idx_from_header(...)`
- `jarvis.sheets_utils.sheet_get_header_row(...)` (async)

Inputs/outputs:
- Mostly string/list transformations.
- `sheet_get_header_row` calls Sheets MCP `values.get` and returns a single header row list.

Invariants / safety notes:
- Header reads can be limited via `max_cols` to avoid pulling stale legacy columns.

Smoke test:

(removed)


## jarvis/memo_enrich.py

Purpose:
Memo “soft-mode” enrichment prompting: after saving a memo, ask follow-up questions if subject/group/details are missing or memo text is too short.

Key entrypoints:
- `jarvis.memo_enrich.prompt_cfg(sys_kv, ...)`
- `jarvis.memo_enrich.needs_enrich(memo, subject, group, cfg)`
- `jarvis.memo_enrich.enrich_prompt(need, cfg)`
- `jarvis.memo_enrich.handle_followup(...)` (async)

Inputs/outputs:
- Inputs:
  - `sys_kv` (runtime config)
  - memo text + optional `subject`, `group`
  - injected helpers (sys_kv parsing, WS send, sheets calls)
- Output:
  - returns `bool` for “handled follow-up”
  - appends an enriched memo row when follow-up completes

Dependencies / injection points:
- `sys_kv` keys:
  - `memo.prompt.enabled`
  - `memo.prompt.require_subject`
  - `memo.prompt.require_group`
  - `memo.prompt.require_details`
  - `memo.prompt.min_chars`
- Sheets MCP: `google_sheets_values_append`

Invariants / safety notes:
- Append-only behavior: enrichment writes a new row rather than mutating the original.
- Follow-up is guarded by a short “agent continuation window”.

Smoke test:
- Save a short memo via `memo_add` and confirm a follow-up prompt is produced.
- Reply with missing fields; confirm a second (enriched) memo row is appended.


## jarvis/daily_brief.py

Purpose:
Render a daily brief string summarizing key state (agents, etc.) while keeping the rendering logic isolated from the web/server runtime.

Key entrypoint:
- `jarvis.daily_brief.render_daily_brief(...)`

Inputs/outputs:
- Inputs:
  - injected data loaders and formatting helpers
- Output:
  - a rendered text brief

Invariants / safety notes:
- Pure rendering; no side-effectful external calls unless passed in via injection.

Smoke test:
- Trigger the daily brief path in the UI / websocket flow and confirm formatting is stable.


## jarvis/tools_router.py

Purpose:
Deterministic backend tool routing for Gemini tool calls that must be executed locally (or forwarded with additional server-side logic), extracted out of `main.py`.

Key entrypoint:
- `jarvis.tools_router.handle_mcp_tool_call(session_id, tool_name, args, deps=...)` (async)

Inputs/outputs:
- Inputs:
  - `session_id`, `tool_name`, `args`
  - `deps` dict that injects all runtime functions, globals, and constants
- Output:
  - tool result payload (JSON-compatible)

Dependencies / injection points:
- Session state (`_SESSION_WS`), feature flags, sys_kv parsing.
- Google Sheets / Calendar / Tasks MCP calls.
- Pending confirmation queue plumbing.

Invariants / safety notes:
- Local tools must never be forwarded to Gemini.
- “Dangerous” tools are queued behind confirmation when configured.

Smoke test:
- Exercise at least:
  - `time_now`
  - `session_last_get`
  - `memo_add`
  - one `pending_*` tool
