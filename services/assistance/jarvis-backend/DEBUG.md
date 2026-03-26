# Jarvis Backend Debug Runbook

This file is intentionally short. The primary runbook lives at `services/assistance/DEBUG.md`.

Operator SSOT:
- `services/assistance/docs/ACTION.md`

API SSOT:
- Prefer the live backend OpenAPI: `GET /openapi.json`

## Quick checks

- `GET /health`
- `GET /agents`
- `GET /debug/agents`
- `GET /daily-brief`
- `GET /reminders?status=all&limit=50`
- `GET /reminders/upcoming?window_hours=48&time_field=notify_at`
- `POST /reminders/{reminder_id}/done`

## Agent wiring

- Agents are discovered from `JARVIS_AGENTS_DIR` (default `/app/agents`).
- Triggers are derived from agent frontmatter `trigger_phrases`.
- Resolved triggers + continuation window are visible via `GET /debug/agents`.

## Reminders

- Local scheduler uses SQLite (`JARVIS_SESSION_DB`).
- Authoritative memory writes go to Weaviate (`WEAVIATE_URL`) and are re-synced on startup.

## Logs

Check container logs for:
- Gemini Live connection errors
- Weaviate request failures (schema, connectivity)
- Embedding errors (missing `GEMINI_API_KEY`/`API_KEY`, invalid embedding model)
