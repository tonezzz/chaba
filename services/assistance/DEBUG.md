
# Services Debug Runbook

This is a practical runbook for debugging the `idc1-assistance` stack.

## Start here (golden path)

Build/deploy:
- If you suspect you are running old images after a redeploy, follow `services/assistance/docs/BUILD.md` (single source of truth).

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

## Service-specific runbooks

- `assistance/jarvis-backend/DEBUG.md`
- `assistance/jarvis-frontend/DEBUG.md`

## Reminder title improvement (optional)
- The backend can rewrite reminder titles to be clearer (best-effort).
- Configure via:
  - `JARVIS_REMINDER_TITLE_MODEL` (preferred)
  - `GEMINI_TEXT_MODEL` (fallback)
