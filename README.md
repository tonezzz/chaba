# Chaba

This repo contains multiple projects. Current focus is **Jarvis / Chaba Assistance**.

## Start here

- Primary overview: `services/assistance/README.md`
- Operator playbook (SSOT): `services/assistance/docs/ACTION.md`
- Build/deploy runbook (SSOT): `services/assistance/docs/BUILD.md`

## Runtime surfaces (Jarvis)

For the authoritative, current API surface, prefer `GET /openapi.json` on the running backend.

- Health: `GET /health`
- WebSocket: `WS /ws/live`
