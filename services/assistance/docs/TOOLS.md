# Tools charts

This file documents the main **tool surfaces** available in the Assistance stack.

Rules:

- No secrets in this file.
- Prefer documenting **stable message schemas** and how they route through the system.

## Chart: Jarvis Live WebSocket (`/jarvis/ws/live`)

The Jarvis UI talks to the backend over a single WebSocket.

Inbound (client -> backend) message types:

| `type` | Purpose | Key fields | Routed to |
|---|---|---|---|
| `text` | Normal chat input | `text` | Gemini Live (unless intercepted by backend sub-agents) |
| `audio` | Microphone audio frame | `data` (base64), optional `mimeType` | Gemini Live realtime input |
| `audio_stream_end` | End of current audio stream | none | Gemini Live realtime input |
| `get_active_trip` | Read sticky session state | none | Backend only |
| `set_active_trip` | Update sticky session state | `active_trip_id`, `active_trip_name` | Backend only |
| `cars_ingest_image` | Send an image for car/plate ingest | `data` (base64), `mimeType`, `request_id` | Backend only |
| `system` | Deterministic backend system tools | `action`, `mode` | Backend only (never forwarded to Gemini) |
| `notes` | Deterministic backend notes tools | `action`, `text` | Backend only (never forwarded to Gemini) |

Outbound (backend -> client) message types (selected):

| `type` | Meaning | Notes |
|---|---|---|
| `state` | connection state | e.g. `connected` |
| `text` | plain text message | model output or backend status lines |
| `transcript` | speech-to-text transcript | `source=input|output` |
| `audio` | PCM audio chunk (base64) | UI plays audio |
| `error` | structured error | `kind`, `message`, optional `detail` |
| `note_created` | note appended to notes sheet | includes best-effort note id |
| `note_prompt` | follow-up needed to complete note | UI can prompt user |

## Chart: Deterministic backend tools (WS messages)

These messages are handled **purely by the backend** and are never forwarded to Gemini.

### System tool: reload

Request schema:

| Field | Values |
|---|---|
| `type` | `system` |
| `action` | `reload` |
| `mode` | `full` \| `memory` \| `knowledge` \| `sys` \| `gems` |

Examples:

```json
{"type":"system","action":"reload","mode":"full"}
```

Expected responses (examples):

- `text`: `Reload System: start`
- `text`: `Reload System: ok | memory=<n> knowledge=<n>`
- `text`: `Reload: already running`
- `error`: `reload_failed` / `invalid_reload_mode`

Notes:

- `memory` and `knowledge` are currently loaded together by the shared sheet loader.

### Notes tools

Request schema:

| Action | Request | Result |
|---|---|---|
| check | `{"type":"notes","action":"check"}` | `text` summary + `Next:` line |
| next | `{"type":"notes","action":"next"}` | `text` single next-step line |
| add | `{"type":"notes","action":"add","text":"..."}` | `note_created` + confirmation |

## Chart: Speech-to-text (STT)

Jarvis does not run a separate STT engine in the backend.

- The UI streams microphone audio to the backend.
- The backend forwards audio to **Gemini Live**.
- Gemini Live returns transcripts and the backend forwards them as:
  - `{"type":"transcript","text":"...","source":"input"}`
  - `{"type":"transcript","text":"...","source":"output"}`

## Chart: Gemini tool calls -> MCP

When Gemini emits tool calls, the backend maps them to MCP servers (1MCP / mcp-bundle) and returns results.

High-level flow:

1) Gemini Live emits `tool_call` with `function_calls`
2) Backend maps tool name -> MCP server/tool
3) Backend calls MCP (HTTP JSON-RPC)
4) Backend returns a `FunctionResponse` to Gemini

Notes:

- Some write-like operations may require confirmation (pending writes).
- MCP environment propagation must be explicit for stdio servers (see `docs/CONFIG.md`).