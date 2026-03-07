# Jarvis Backend (Architecture)

## What it is
Python/FastAPI backend container (Gemini Live bridge + tool/router logic).

## Runtime expectations
- Exposes `GET /health`
- Exposes `WS /ws/live`

## WebSocket contract (high-level)
- Client provides `session_id` via query param: `WS /ws/live?session_id=...`
- Backend may emit an `active_trip` message on connect.

## Session state
- Session identity is provided by the frontend (`session_id`).
- Per-session state must survive WS reconnects (e.g. `active_trip`).
- Session store path must be configurable by env (e.g. `JARVIS_SESSION_DB`) and should be mounted to a volume if persistence across container restarts is required.

## TRIP integration (wiring)
- Configure:
  - `TRIP_BASE_URL` (default `http://trip:8000` in the `idc1-assistance` stack)
  - `TRIP_API_TOKEN` (optional; used for `X-Api-Token`)

## Guardrails
- TRIP writes (POST/PUT/PATCH/DELETE) must be gated behind explicit user confirmation (two-phase propose/commit).
