# Assistance Services Structure Policy

## Purpose
The `/services/assistance/` tree is the source-of-truth for all *Assistance* application code that is deployed via the `idc1-assistance` stack (Jarvis, TRIP, MCP servers, and any future assistance services).

This policy exists to:
- Keep application code separate from deployment configuration.
- Standardize paths for CI builds (GHCR) and Portainer deploys.
- Make it easy to add new services (e.g. `mcp-*`) without ambiguity.

## High-level layout
```
/services/assistance/
  jarvis-backend/
  jarvis-frontend/
  trip/
  mcp-servers/
```

### `/services/assistance/jarvis-backend/`
- **What it is**: Python/FastAPI backend container (Gemini Live bridge + tool/router logic).
- **Must contain**:
  - `Dockerfile`
  - `requirements.txt`
  - Application code (recommend `app/` as the Python package root)
- **Runtime expectations**:
  - Exposes `GET /health`
  - Exposes `WS /ws/live`
- **Session state**:
  - Session identity is provided by the frontend (e.g. `session_id`) and must be persisted such that the per-session `active_trip` survives WS reconnects.

### `/services/assistance/jarvis-frontend/`
- **What it is**: Vite/React frontend built into an Nginx container.
- **Must contain**:
  - `Dockerfile.frontend`
  - `nginx.jarvis.conf`
  - Vite/React sources (`App.tsx`, `index.html`, `components/`, `services/`, etc.)
- **Runtime expectations**:
  - Served under `/jarvis/` base path in production.
  - WebSocket client connects to backend at `/jarvis/ws/live` (via Caddy rewrite to backend `/ws/live`).
- **Confirmation UX**:
  - Frontend is the primary place for confirmation UI (Confirm button).
  - Typed fallback confirmation (e.g. `confirm <id>`) is supported.

### `/services/assistance/trip/`
- **What it is**: TRIP application container/service (itskovacs/TRIP).
- **Persistence**:
  - TRIP persistent storage must be mounted to `/app/storage`.
- **Networking**:
  - Internal-only service access from Jarvis backend (no public ingress unless explicitly required).
- **Auth**:
  - Prefer TRIP API token auth (`X-Api-Token`) for Jarvis-to-TRIP calls.

### `/services/assistance/mcp-servers/`
- **What it is**: A containerized collection of MCP servers (one subfolder per server).
- **Folder naming**:
  - `mcp-servers/<server-name>/`
- **Persistence**:
  - Each MCP server should declare its own named volume(s) or bind mount(s) for caches/state.
- **Networking**:
  - Default: internal-only.
  - Public exposure must be explicit and documented.

## Deployment configuration policy
Deployment configuration lives under:
- `/stacks/idc1-assistance/` (Portainer stack)

Rules:
- `/stacks/idc1-assistance/` should contain deployment artifacts only (compose, env examples, notes).
- Application source code must not be placed in `/stacks/`.

## CI/CD + build contexts
Images are built and pushed to GHCR and then pulled by Portainer.

Rules:
- Build contexts in GitHub Actions must reference folders under `/services/assistance/*`.
- Image naming remains stable (e.g. `jarvis-backend`, `jarvis-frontend`), and tags follow the branch.

## Persistence conventions
- Anything that must survive container restarts must live on a named volume or bind mount.
- Standard expectations:
  - **TRIP**: `/app/storage`
  - **Jarvis backend**: session state store (path to be documented in `jarvis-backend/` once implemented)
  - **MCP servers**: server-specific paths documented per server

## Safety / guardrails
- Any write to external systems (including TRIP writes: POST/PUT/PATCH/DELETE) must be gated behind explicit user confirmation.
- The backend must support a two-phase flow:
  - **Propose**: create a `pending_action` (no write)
  - **Commit**: execute only when given a valid `confirmation_id`

## Source-of-truth
If there is a mismatch between stack configuration and service folders, the service folders under `/services/assistance/` are considered authoritative, and the stack config should be updated to match.
