
# Services Debug Runbook

This is a practical runbook for debugging the `idc1-assistance` stack.

## Start here (golden path)

Build/deploy:
- If you suspect you are running old images after a redeploy, follow `services/assistance/docs/BUILD.md` (single source of truth).

Operator SSOT:
- `services/assistance/docs/ACTION.md`

API SSOT:
- Prefer the live backend OpenAPI: `GET /openapi.json`

Note:
- The endpoint list below is a practical checklist and may be incomplete; treat `/openapi.json` as authoritative.

### Jarvis Backend
- `GET /health`
- `GET /agents`
- `GET /debug/agents`
- `GET /daily-brief`
- `GET /reminders?status=pending&include_hidden=false`
- `GET /reminders/upcoming?window_hours=48&time_field=notify_at`
- `POST /reminders/{reminder_id}/done`
- `POST /reminders/{reminder_id}/later?days=1`
- `GET /reminders/{reminder_id}/reschedule/suggest`
- `POST /reminders/{reminder_id}/reschedule?notify_at=<unix_ts>`
- `GET /agents` (ensure `follow_news` is discovered)
- `GET /daily-brief` (ensure `follow_news` status payload shows up after refresh)

### Jarvis Frontend
- Confirm the SPA loads
- Confirm WebSocket connects to backend and receives `{type: "state", state: "connected"}`

Operation Log debugging:

- Expand any entry to see:
  - `trace_id` (correlates a user action across frontend/backend logs)
  - WS metadata (`type`, `instance_id`)
  - raw WS JSON payload
- Use the `show debug` toggle to reveal debug-only entries (e.g. transcript events).

### Weaviate
- Readiness:
  - `GET http://weaviate:8080/v1/.well-known/ready`

Note: Weaviate readiness returns HTTP 200 with an empty body; container healthchecks should only check the status code (not grep for `true`).

### Deep research worker (optional)
- `GET http://deep-research-worker:8030/health`

Common failure mode:
- `sqlite3.OperationalError: unable to open database file`
  - The worker stores job state in SQLite at `DEEP_RESEARCH_DB` (stack default: `/data/deep_research.sqlite`).
  - Ensure the `/data` mount exists and is writable by the container's non-root user.

## Common issues

### WebSocket connects but no responses
- Confirm backend is reachable from the reverse proxy and the WS URL is correct.
- Check backend logs for errors around Gemini Live connect and tool calls.

If the UI shows a response you want to correlate with logs:

- Copy the `trace_id` from the expanded Operation Log entry.
- Filter logs with:
  - `./scripts/collect-idc1-assistance-evidence.sh <trace_id>`

### WebSocket disconnects immediately after Initialize
- Symptom: backend logs show `WebSocket /ws/live ... [accepted]` + `gemini_live_connect ...` then `connection closed`.
- Confirm the running backend image contains the latest diagnostics (look for `ws_live_tasks_done` / `ws_live_task_failed` markers).
- If using Portainer:
  - Ensure redeploy is configured to pull the latest image digest ("always pull" / re-pull image).
- Check backend logs for:
  - `gemini_live_connect_build_failed` / `gemini_live_session_failed`
  - `ws_live_exception`
- Common root causes:
  - Missing/invalid `GEMINI_API_KEY` / `API_KEY` (401/403)
  - Quota / billing limits (429 RESOURCE_EXHAUSTED)
  - Unsupported model name in `GEMINI_LIVE_MODEL`

### Gemini Live fails mid-session but the UI should stay connected
- Expected behavior:
  - The backend should keep `WS /ws/live` open.
  - The backend should emit a structured error event:
    - `{ "type": "error", "message": "gemini_session_failed", ... }`
  - Deterministic sub-agent handlers (e.g. `reminder setup: ...`) should still work.

Common structured error:
- `gemini_live_model_not_found`
  - Means the configured `GEMINI_LIVE_MODEL` is not accessible for the current API key.
  - Fix: set `GEMINI_LIVE_MODEL` to a model your key can access.

### Agent trigger not firing
- Confirm the agent is loaded:
  - `GET /agents`
- Confirm triggers resolved as expected:
  - `GET /debug/agents`
- Confirm your agent MD includes `trigger_phrases` and that your message contains the phrase.
- If a sub-agent recently ran, remember the continuation window may route follow-ups without re-triggering.

Quick smoke commands:
- `follow news refresh`
- `follow news`
- `report: <summary_id>`

### Reminders are missing (tomorrow/next day)
- Reference overview:
  - `services/assistance/docs/REMINDERS.md`
- Check history vs upcoming:
  - `GET /reminders?status=all&limit=50`
  - `GET /reminders/upcoming?window_hours=72&time_field=notify_at`
- If upcoming is empty but you expect reminders:
  - Confirm `notify_at` and timezone logic.
  - Confirm the reminder isn't hidden via `hide_until`:
    - `GET /reminders?status=pending&include_hidden=true`
  - If logs show `no such column: hide_until`:
    - Your persisted `JARVIS_SESSION_DB` likely predates the migration.
    - Redeploy a jarvis-backend image that includes the `reminders` table migration logic.
    - Confirm the DB mount is writable so the migration can rebuild the table if needed.
  - Confirm the SQLite DB is persisted (volume/bind mount for `JARVIS_SESSION_DB`).
  - If `WEAVIATE_URL` is configured, reminder retrieval prefers Weaviate; confirm Weaviate contains the reminder objects.

### Follow News agent quick usage
- List focus:
  - Send: `โฟกัสข่าว`
- Add/remove focus:
  - `โฟกัสข่าว เพิ่ม: <คำ/หัวข้อ>`
  - `โฟกัสข่าว ลบ: <คำ/หัวข้อ>`
- Refresh summaries:
  - `ติดตามข่าว รีเฟรช`
- List stored summaries:
  - `ติดตามข่าว`
- Report a specific stored summary:
  - `รายงานข่าว: <summary_id>`

### Too many reminders in Today
- Use `later` (hide until) to temporarily hide an item:
  - `POST /reminders/{reminder_id}/later?days=1`
- Hidden reminders are excluded by default from list/upcoming.
  - To include hidden reminders:
    - `GET /reminders?status=pending&include_hidden=true`

### Reminder helper (WS quick commands)
- `reminder add: <text>`
- `reminder list pending`
- `reminder done: <reminder_id>`
- `reminder later: <reminder_id> 1`
- `reminder reschedule: <reminder_id> tomorrow 09:00`
- `reminder delete: <reminder_id>`

### Reschedule an overdue reminder
- Get a backend-suggested next time (uses user TZ, defaults to next morning 08:30 when it's late):
  - `GET /reminders/{reminder_id}/reschedule/suggest`
- Apply the new schedule:
  - `POST /reminders/{reminder_id}/reschedule?notify_at=<unix_ts>`

### Weaviate is up but memory writes fail
- Confirm `WEAVIATE_URL` points to `http://weaviate:8080` inside the Docker network.
- Confirm schema exists:
  - `GET http://weaviate:8080/v1/schema/JarvisMemoryItem`
- If failures mention embedding:
  - Confirm `GEMINI_API_KEY`/`API_KEY` is set.
  - Confirm `GEMINI_EMBEDDING_MODEL` is valid.

### MCP image pipeline returns errors
- If you see errors like `RESOURCE_EXHAUSTED` or `Quota exceeded` from Gemini image models:
  - This is typically a quota/billing issue (429).
  - Check `mcp-image-pipeline` logs for the upstream error body.
- If you see authentication errors:
  - Confirm `GEMINI_API_KEY` is set for `mcp-image-pipeline`.

## Logs

Look at logs for these containers first:
- `jarvis-backend`
- `jarvis-frontend` (reverse proxy errors if any)
- `weaviate`

If you are debugging MCP image pipeline routing, also check:
- `mcp-image-pipeline`

## WS record/replay (repro tooling)

To capture a reproducible trace of WS traffic:

- Set env:
  - `JARVIS_WS_RECORD=1`
  - optional `JARVIS_WS_RECORD_PATH=/tmp/jarvis-ws.jsonl`

Replay captured inbound text messages through backend dispatch:

- `python3 services/assistance/jarvis-backend/ws_replay.py /tmp/jarvis-ws.jsonl`

## sys_kv_set (system sheet KV writes)

`sys_kv_set` is a deterministic websocket system action that writes a single key/value pair into the **system Google Sheet**.

### Preconditions / safety gate

- Writes are **disabled by default**.
- The backend requires this key in the system sheet:
  - `sys_kv.write.enabled=true`
- If the key is missing or set to falsey, the backend returns a structured error:
  - `kind=sys_kv_write_disabled`

### Correct ways to trigger

Use one of these (in priority order):

1) UI composer command:
   - `/sys set <key>=<value>`
   - Dry-run:
     - `/sys dry <key>=<value>`

2) Frontend API call (when you have a reference to the LiveService instance):
   - `sendSysKvSet(key, value, { dry_run })`

### Sheets validation: toggle keys use the `enabled` column

Some system sheet tabs enforce validation that can reject boolean-looking values in the `value` column (for example, writing `FALSE` may fail even if `TRUE` succeeds).

Convention:

- Toggle keys:
  - `*.enabled`
  - `feature.*`
- Should be driven by the **`enabled` column** (TRUE/FALSE), not by putting booleans into the `value` column.

Usage:

- Enable:
  - `/sys set some.flag.enabled=TRUE`
- Disable:
  - `/sys set some.flag.enabled=FALSE`

Backend behavior:

- For toggle keys, the backend accepts `TRUE/FALSE` input and writes lowercase `true/false` into the sheet’s `enabled` column (and avoids writing boolean values into `value`).

### Common mistake: pasting JSON into chat

If you paste JSON into the composer, it is typically sent as a **chat message**:

```json
{ "type": "text", "text": "{ \"type\": \"system\", ... }" }
```

That will **not** execute the system action; it is just model input.

To execute a `sys_kv_set`, the outbound websocket frame must be the system envelope itself:

```json
{ "type": "system", "action": "sys_kv_set", "key": "...", "value": "...", "dry_run": false }
```

### What “success” looks like

- Backend emits a `type="text"` line like:
  - `sys_kv_set ok: <key>=<value>`
- Backend refreshes `sys_kv` in memory (best-effort) so subsequent reads reflect the new value.

If the UI says “ok” but you don’t see the sheet change:

- Verify you’re looking at the same spreadsheet/tab as the running backend:
  - `CHABA_SYSTEM_SPREADSHEET_ID`
  - `CHABA_SYSTEM_SHEET_NAME`
- Confirm there is no competing writer (another instance) overwriting the key.
- Capture the `trace_id` and pull evidence:
  - `./scripts/collect-idc1-assistance-evidence.sh <trace_id>`

## Operation Log text chunk grouping (frontend)

Jarvis can receive rapid-fire small text fragments (especially from voice transcription or model streaming). To keep the Operation Log readable, the frontend merges short adjacent chunks.

### Where it happens

- `services/assistance/jarvis-frontend/App.tsx`
  - In the `liveService.current.onMessage` handler, inside the `setMessages(...)` reducer.

### Current merge heuristic (high level)

- Only considers merging when:
  - Same role (`model` or `system`)
  - Messages arrive within ~1 second
  - Text is short and single-line
  - Previous chunk doesn’t look like a sentence boundary

If you need to tune the UX, adjust:

- The time window (ms)
- The “looks like chunk” max length
- Sentence boundary detection regex

## Frontend contract tests

The frontend includes a small Vitest contract suite for WS event rendering:

- `cd services/assistance/jarvis-frontend`
- `npm test`

## Service-specific runbooks

- `assistance/jarvis-backend/DEBUG.md`
- `assistance/jarvis-frontend/DEBUG.md`

## Reminder title improvement (optional)
- The backend can rewrite reminder titles to be clearer (best-effort).
- Configure via:
  - `JARVIS_REMINDER_TITLE_MODEL` (preferred)
  - `GEMINI_TEXT_MODEL` (fallback)
