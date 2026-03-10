
# Services Debug Runbook

This is a practical runbook for debugging the `idc1-assistance` stack.

## Start here (golden path)

### Jarvis Backend
- `GET /health`
- `GET /agents`
- `GET /debug/agents`
- `GET /daily-brief`
- `GET /reminders/upcoming?window_hours=48&time_field=notify_at`
- `POST /reminders/{reminder_id}/done`

### Jarvis Frontend
- Confirm the SPA loads
- Confirm WebSocket connects to backend and receives `{type: "state", state: "connected"}`

### Weaviate
- Readiness:
  - `GET http://weaviate:8080/v1/.well-known/ready`

Note: Weaviate readiness returns HTTP 200 with an empty body; container healthchecks should only check the status code (not grep for `true`).

### Deep research worker (optional)
- `GET http://deep-research-worker:8030/health`

## Common issues

### WebSocket connects but no responses
- Confirm backend is reachable from the reverse proxy and the WS URL is correct.
- Check backend logs for errors around Gemini Live connect and tool calls.

### Agent trigger not firing
- Confirm the agent is loaded:
  - `GET /agents`
- Confirm triggers resolved as expected:
  - `GET /debug/agents`
- Confirm your agent MD includes `trigger_phrases` and that your message contains the phrase.
- If a sub-agent recently ran, remember the continuation window may route follow-ups without re-triggering.

### Reminders are missing (tomorrow/next day)
- Check history vs upcoming:
  - `GET /reminders?status=all&limit=50`
  - `GET /reminders/upcoming?window_hours=72&time_field=notify_at`
- If upcoming is empty but you expect reminders:
  - Confirm `notify_at` and timezone logic.
  - Confirm the SQLite DB is persisted (volume/bind mount for `JARVIS_SESSION_DB`).
  - If `WEAVIATE_URL` is configured, reminder retrieval prefers Weaviate; confirm Weaviate contains the reminder objects.

### Weaviate is up but memory writes fail
- Confirm `WEAVIATE_URL` points to `http://weaviate:8080` inside the Docker network.
- Confirm schema exists:
  - `GET http://weaviate:8080/v1/schema/JarvisMemoryItem`
- If failures mention embedding:
  - Confirm `GEMINI_API_KEY`/`API_KEY` is set.
  - Confirm `GEMINI_EMBEDDING_MODEL` is valid.

## Logs

Look at logs for these containers first:
- `jarvis-backend`
- `jarvis-frontend` (reverse proxy errors if any)
- `weaviate`

## Service-specific runbooks

- `assistance/jarvis-backend/DEBUG.md`
- `assistance/jarvis-frontend/DEBUG.md`
