# Assistance stack config (idc1-assistance)

This file documents **effective runtime configuration** for the `idc1-assistance` stack (Jarvis frontend+backend+Weaviate) on the Docker host.

Rules:

- No secrets in this file.
- Prefer documenting **actual bind ports/URLs** that operators use.
- Compose defaults do not override values configured in **Portainer stack env**.

Operator SSOT:

- `services/assistance/docs/ACTION.md`

API SSOT:

- Prefer the live backend OpenAPI: `GET /openapi.json`

## Host endpoints (effective)

- Jarvis UI:
  - `http://127.0.0.1:18080/jarvis/`
- Jarvis backend health:
  - `http://127.0.0.1:18018/health`
- Weaviate (internal to stack network):
  - `http://weaviate:8080`

## Logs endpoints

Jarvis backend accepts best-effort UI log appends and serves daily UI/WS logs via HTTP.

- UI log append:
  - `POST http://127.0.0.1:18018/jarvis/api/logs/ui/append`
- Read UI log:
  - `GET http://127.0.0.1:18018/jarvis/api/logs/ui/today`
- Read WS log:
  - `GET http://127.0.0.1:18018/jarvis/api/logs/ws/today`

Notes:

- Public UI endpoint `https://assistance.idc1.surf-thailand.com/jarvis/` is served via edge proxy.
- Backend HTTP routes (logs + memo + health) should be exposed via edge proxy prefix:
  - public: `https://assistance.idc1.surf-thailand.com/jarvis/api/...`
  - proxy behavior: `handle_path /jarvis/api/*` -> `http://127.0.0.1:18018` (strip `/jarvis/api`)

WebSocket:

- public: `wss://assistance.idc1.surf-thailand.com/jarvis/ws/live`
- backend internal: `/ws/live` (edge proxy strips `/jarvis/ws` before proxying)

Public examples (when edge proxy is configured):

```bash
curl -fsS https://assistance.idc1.surf-thailand.com/jarvis/api/health

curl -fsS https://assistance.idc1.surf-thailand.com/jarvis/api/logs/ui/today
```

## Ports (host binds)

- `127.0.0.1:18080` -> Jarvis frontend
- `127.0.0.1:18018` -> Jarvis backend

## Source-of-truth locations

- Stack compose (split stacks):
  - `stacks/idc1-assistance-infra/docker-compose.yml`
  - `stacks/idc1-assistance-mcp/docker-compose.yml`
  - `stacks/idc1-assistance-core/docker-compose.yml`
  - `stacks/idc1-assistance-workers/docker-compose.yml`
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
  - **For full voice (audio in + audio out)**: Use native-audio models
  - **For voice input with text output**: Use `gemini-3.1-flash-lite`
  - **For text-only Live mode**: Can use any Gemini model
  - **Available models for voice input**:
    - `gemini-3.1-flash-lite` - Audio input, TEXT output (uses TTS for responses)
    - `gemini-2.5-flash-native-audio-latest` - Audio input + output (recommended)
    - `gemini-2.5-flash-native-audio-preview-12-2025` - Audio input + output
    - `lyria-realtime-exp` - Audio input + output

Reminders:

- **Voice vs Text in Live Mode**: 
  - `gemini-3.1-flash-lite`: Audio input (STT), TEXT output (backend TTS speaks responses)
  - Native-audio models (e.g., `gemini-2.5-flash-native-audio-latest`): Audio input AND audio output (model speaks directly)
  - Non-audio models (e.g., `gemini-2.5-flash`, `gemini-2.5-pro`): Text input only in Live mode

Debugging:

- `JARVIS_WS_RECORD`
  - when set to `1`, the backend records WS messages to JSONL (inbound + outbound)
- `JARVIS_WS_RECORD_PATH`
  - optional path for the JSONL file
  - default: `/tmp/jarvis-ws.jsonl`

Notes:

- Gemini model IDs may appear with or without a `models/` prefix. For Gemini Live, prefer unprefixed model IDs (some endpoints reject `models/<id>`).
- On successful `/jarvis/ws/live` connection the backend emits a short day/date/time greeting as a normal `text` message (language matched).

## Speech-to-text (STT) + transcripts

### Primary STT (Gemini Live)

- **Where STT happens**
  - STT is performed by **Gemini Live** based on the microphone audio stream sent from the frontend.

- **How transcripts flow**
  - The frontend streams audio frames to the backend over WebSocket (`/jarvis/ws/live`).
  - The backend forwards audio into the Gemini Live session.
  - Gemini Live returns transcript events; the backend forwards them to the UI as WS messages:
    - `{"type":"transcript","text":"...","source":"input"}` (what the user said)
    - `{"type":"transcript","text":"...","source":"output"}` (what Jarvis said)

- **Voice commands (e.g. Reload System)**
  - The backend listens for **input transcripts** and dispatches local command handlers (sub-agents) before the text is treated as normal chat.
  - This is how voice phrases like `Reload System` can trigger backend actions even if the model would otherwise reply conversationally.

### Sidecar STT (for native-audio models)

When using **native-audio models** (e.g., `gemini-2.5-flash-native-audio-preview`), Gemini Live receives audio directly and performs STT internally. However, for logging and comparison purposes, Jarvis runs a **sidecar STT** that transcribes the same audio stream via a separate Gemini API call.

**Behavior:**
- Sidecar STT runs only for native-audio models
- Transcripts are displayed in the UI for comparison/logging
- **When Live is working, sidecar transcripts are NOT forwarded to Gemini** (`forward_to_gemini: false`)
- This prevents duplicate input while still showing the STT quality for debugging

**Circuit Breaker:**
- After 5 consecutive STT errors, sidecar pauses for 30 seconds
- This preserves API quota and session stability
- Errors are isolated - they never crash the main Live session
- Circuit resets on successful transcription

**Environment variables:**

- `JARVIS_SIDECAR_STT_MODEL` - Model used for sidecar transcription
  - default: `gemini-flash-lite-latest` (higher rate limits than flash-latest)
- `JARVIS_SIDECAR_STT_CHUNK_S` - Audio chunk size in seconds (default: 1.5)
- `JARVIS_SIDECAR_STT_INTERVAL_S` - Transcription interval (default: 1.0)
- `JARVIS_SIDECAR_STT_OVERLAP_S` - Overlap between chunks (default: 0.5)
- `JARVIS_SIDECAR_STT_FINAL_MAX_S` - Max seconds for final flush (default: 12.0)
- `JARVIS_SIDECAR_STT_TIMEOUT_S` - Per-call timeout (default: 20.0)
- `JARVIS_SIDECAR_STT_FINAL_TIMEOUT_S` - Final flush timeout (default: 45.0)
- `JARVIS_SIDECAR_STT_LANGUAGE` - Language hint (optional)
- `JARVIS_SIDECAR_STT_ENABLE_PARTIALS` - Enable partial transcripts (default: false)

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

Operator SSOT:

- See `services/assistance/docs/ACTION.md` for the deployed verification checklist and exact commands.

## Collect debug evidence (single command)

Operator SSOT:

- See `services/assistance/docs/ACTION.md` for the current evidence collection commands and how to use `trace_id`.
