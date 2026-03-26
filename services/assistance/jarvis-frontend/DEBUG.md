# Jarvis Frontend Debug Runbook

This file is intentionally short. The primary runbook lives at `services/assistance/DEBUG.md`.

Operator SSOT:
- `services/assistance/docs/ACTION.md`

API SSOT:
- Prefer the live backend OpenAPI: `GET /openapi.json`

## Quick checks

- Confirm the SPA loads.
- Confirm the frontend is using the correct base path (production typically served under `/jarvis/`).
- Confirm WebSocket connects and receives `{type: "state", state: "connected"}`.

## Common symptoms

### No audio / mic issues

- Check browser permissions for microphone.
- Check device input selection.

### WebSocket fails to connect

- Confirm reverse proxy rules rewrite `/jarvis/ws/live` to backend `/ws/live`.
- Confirm the backend is reachable from the host mapping.

## Reference

- Reverse proxy snippet: `CADDY_JARVIS_SNIPPET.md`
- Architecture index: `ARCHITECTURE.md`
