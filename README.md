# Chaba

This repo contains multiple projects. Current focus is **Jarvis / Chaba Assistance**.

## 📚 Documentation

> **New Policy:** All documentation lives in the [MCP Wiki](http://localhost:3008)  
> See: [`docs/WIKI_DOCUMENTATION_POLICY.md`](docs/WIKI_DOCUMENTATION_POLICY.md)

- 🌐 **Wiki (Primary):** http://localhost:3008
- 🤖 **Auto-Research:** `python /workspace/smart-research.py "[topic]"`
- 📝 **Policy:** [`docs/WIKI_DOCUMENTATION_POLICY.md`](docs/WIKI_DOCUMENTATION_POLICY.md)

## Start here

- Primary overview: `services/assistance/README.md`
- Operator playbook (SSOT): `services/assistance/docs/ACTION.md`
- Build/deploy runbook (SSOT): `services/assistance/docs/BUILD.md`

## Runtime surfaces (Jarvis)

For the authoritative, current API surface, prefer `GET /openapi.json` on the running backend.

- Health: `GET /health`
- WebSocket: `WS /ws/live`
