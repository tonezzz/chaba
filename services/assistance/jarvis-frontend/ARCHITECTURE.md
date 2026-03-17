# Jarvis Frontend (Architecture)

## What it is
Vite/React frontend built into an Nginx container.

## Runtime expectations
- Served under `/jarvis/` base path in production.
- WebSocket client connects to the backend at `/jarvis/ws/live` (via reverse proxy rewrite to backend `/ws/live`).

## Session identity
- Frontend generates/persists a stable `session_id` (e.g. in `localStorage`) and passes it as `?session_id=...` on the WebSocket URL.

## Confirmation UX
- Frontend is the primary place for confirmation UI.
- Typed fallback confirmation (e.g. `confirm <id>`) is supported.

## Debug UI
- Includes a small panel that displays `session_id`.

Operation Log:

- Each inbound/outbound entry can be expanded to view:
  - `trace_id`
  - WS metadata (`type`, `instance_id`)
  - raw WS JSON payload
- A `show debug` toggle reveals additional debug-only entries (e.g. transcript events).
