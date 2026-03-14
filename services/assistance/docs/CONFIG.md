# Assistance stack config (idc1-assistance)

This file documents **effective runtime configuration** for the `idc1-assistance` stack (Jarvis frontend+backend+Weaviate) on the Docker host.

Rules:

- No secrets in this file.
- Prefer documenting **actual bind ports/URLs** that operators use.
- Compose defaults do not override values configured in **Portainer stack env**.

## Host endpoints (effective)

- Jarvis UI:
  - `http://127.0.0.1:18080/jarvis/`
- Jarvis backend health:
  - `http://127.0.0.1:18018/health`
- Reminders API:
  - `http://127.0.0.1:18018/reminders`
- Weaviate (internal to stack network):
  - `http://weaviate:8080`

## Ports (host binds)

- `127.0.0.1:18080` -> Jarvis frontend
- `127.0.0.1:18018` -> Jarvis backend

## Source-of-truth locations

- Stack compose:
  - `stacks/idc1-assistance/docker-compose.yml`
- Stack env template:
  - `stacks/idc1-assistance/.env.example`
- Portainer control-plane + MCP config:
  - `stacks/idc1-portainer/docs/CONFIG.md`

## Environment variables (non-secret overview)

These are set via compose defaults and/or Portainer stack env:

- `WEAVIATE_URL`
  - example: `http://weaviate:8080`
- `GEMINI_LIVE_MODEL`
  - example: `gemini-2.5-flash-native-audio-preview-12-2025`

Reminders:

- `JARVIS_LEGACY_REMINDER_NOTIFICATIONS_ENABLED`
  - when set to `1`/`true`, enables the legacy local reminder scheduler loop (SQLite due-check + WS broadcast)
  - default is disabled (`0`) to avoid double notifications after the Google Calendar cutover

Debugging:

- `JARVIS_WS_RECORD`
  - when set to `1`, the backend records WS messages to JSONL (inbound + outbound)
- `JARVIS_WS_RECORD_PATH`
  - optional path for the JSONL file
  - default: `/tmp/jarvis-ws.jsonl`

Notes:

- Gemini model IDs may appear with or without a `models/` prefix. For Gemini Live, prefer unprefixed model IDs (some endpoints reject `models/<id>`).
- On successful `/ws/live` connection the backend emits a short day/date/time greeting as a normal `text` message (language matched).

Secrets (must be provided via Portainer stack env or host env, never committed):

- `GEMINI_API_KEY`

## MCP (1MCP) environment propagation (important)

When using `mcp-bundle` (1MCP) with stdio MCP servers:

- Child MCP servers do **not** automatically inherit all container env.
- If a server needs environment variables (e.g. `GOOGLE_CALENDAR_CLIENT_ID`), you must provide a per-server `env` block in the 1MCP config (`mcp.json`).

Portainer / compose interpolation gotcha:

- If you generate `mcp.json` via a heredoc inside `docker-compose.yml`, do not write `${VAR}` directly inside the JSON.
- Portainer/docker-compose may expand `${VAR}` at deploy time (often to an empty string), resulting in broken runtime config.
- Use escaped placeholders like `$${VAR}` so the literal `${VAR}` is written into the file and then substituted at runtime.

## Deploy (hands-off)

Canonical flow on the Docker host:

- `./scripts/deploy-idc1-assistance.sh`

This script:

- waits for latest successful GH Actions publish run
- pulls images
- redeploys via Portainer CE HTTP API when digests changed
- verifies image digests and health

## Verification checklist (post-redeploy)

- Backend health:
  - `curl -fsS http://127.0.0.1:18018/health`
- Reminders list:
  - `curl -fsS 'http://127.0.0.1:18018/reminders?status=pending&limit=5'`
- Backend logs (recent):
  - `docker logs --since 15m --tail 400 idc1-assistance-jarvis-backend-1`

## Collect debug evidence (single command)

After reproducing an issue, collect a snapshot of the current host state:

- `./scripts/collect-idc1-assistance-evidence.sh`

If you have a `trace_id` from the Operation Log, filter backend logs to just that trace:

- `./scripts/collect-idc1-assistance-evidence.sh <trace_id>`
