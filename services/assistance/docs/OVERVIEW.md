# Overview (Assistance)

Purpose:
- Provide a single always-updated overview of the **assistance** system (architecture + key flows).
- Keep a current diagram that matches what is deployed.

## Scope

In scope:
- `services/assistance/jarvis-backend`
- `services/assistance/deep-research-worker`
- assistance UI (served under the assistance ingress)
- MCP bundle as used by assistance
- external dependencies used by assistance (GitHub, Google APIs, Sheets)

Out of scope:
- other stacks/services in this repo that are not part of assistance

## Environments

- `idc1` (primary deploy)

## Current architecture (latest)

```mermaid
graph TD
  UI[Jarvis UI] -->|WS /ws/live| BE[jarvis-backend]
  UI -->|HTTP /jarvis/api/*| BE
  BE -->|HTTP| MCP[1MCP / MCP gateway]
  BE -->|HTTP| GH[GitHub API]
  BE -->|HTTP| Google[Google APIs]
  BE -->|HTTP| Sheets[Google Sheets]
  BE -->|HTTP| Weaviate[Weaviate (optional)]
  BE -->|SQLite| DB[(Session DB)]
  BE -->|HTTP| DR[deep-research-worker (optional)]
```

## Links

- Operator playbook (SSOT): `services/assistance/docs/ACTION.md`
- Build/deploy (SSOT): `services/assistance/docs/BUILD.md`
- System notes: `services/assistance/docs/SYSTEM.md`
- WS protocol/tools: `services/assistance/docs/TOOLS.md`
- Skills Sheet SSOT routing: `services/assistance/docs/SYSTEM.md`

## Conventions

- Prefer runtime API truth from `GET /openapi.json` on the deployed backend.
- Keep operator procedures in `ACTION.md` and link here instead of duplicating.

## Last updated

- <ts>
- <link to Issue/PR/commit>
