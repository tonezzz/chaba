# Assistance Services

## What this folder is
The `/services/assistance/` tree is the source-of-truth for all *Assistance* application code deployed via the `idc1-assistance` stack.

## Start here
- `CONCEPT.md`
- `TOOLS_POLICY.md`
- `MEMORY_POLICY.md`

## Authoritative runtime surfaces (Jarvis)
- Jarvis Backend (HTTP):
  - `GET /health`
  - `GET /agents`
  - `GET /debug/agents`
  - `GET /daily-brief`
  - `GET /reminders`
  - `GET /reminders/upcoming`
- Jarvis Backend (WebSocket):
  - `WS /ws/live`

## Agents
- Agent definitions live under:
  - `jarvis-backend/agents/*.md`
- Trigger wiring and handlers live in:
  - `jarvis-backend/main.py`

## Service docs
- `jarvis-backend/ARCHITECTURE.md`
- `jarvis-frontend/ARCHITECTURE.md`
- `trip/ARCHITECTURE.md`
- `mcp-servers/ARCHITECTURE.md`

## Memory (current direction)
- Authoritative store: Weaviate (internal-only container in the `idc1-assistance` stack)
- Operational cache/scheduler: Jarvis backend SQLite (`JARVIS_SESSION_DB`)

## Deployment
- Stack configuration lives under:
  - `/stacks/idc1-assistance/`
