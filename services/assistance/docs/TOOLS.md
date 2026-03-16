# Tools charts

```mermaid
flowchart TB
  UI[Jarvis Frontend] -- WS /jarvis/ws/live --> BE[Jarvis Backend]

  subgraph Deterministic Tools (Mode B)
    BE --> SYS[system.*]
    BE --> NOTES[notes.*]
    BE --> REM[reminders.*]
  end

  BE -- audio/text --> GL[Gemini Live]
  GL -- tool_call --> BE
  BE -- MCP JSON-RPC --> MCP[mcp-bundle / 1MCP servers]
  MCP -- results --> BE
  BE -- FunctionResponse --> GL

  BE -- WS events --> UI
```

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
| `reminders` | Deterministic backend reminders tools | `action`, `text`, `reminder_id`, `when` | Backend only (never forwarded to Gemini) |

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
- Frontend can do **smart mapping** (typed/voice) to select `mode` based on keywords like `memory`, `knowledge`, `gems`.

### Notes tools

Request schema:

| Action | Request | Result |
|---|---|---|
| check | `{"type":"notes","action":"check"}` | `text` summary + `Next:` line |
| next | `{"type":"notes","action":"next"}` | `text` single next-step line |
| add | `{"type":"notes","action":"add","text":"..."}` | `note_created` + confirmation |

### Reminders tools

Request schema (selected):

| Action | Request | Result |
|---|---|---|
| add | `{"type":"reminders","action":"add","text":"..."}` | `planning_item_created` (calendar event or task) |
| list | `{"type":"reminders","action":"list","status":"pending"}` | `reminders_list` with `items` |
| done | `{"type":"reminders","action":"done","reminder_id":"..."}` | `reminders_done` |
| delete | `{"type":"reminders","action":"delete","reminder_id":"..."}` | `reminders_deleted` |
| later | `{"type":"reminders","action":"later","reminder_id":"...","days":2}` | `reminders_later` |
| reschedule | `{"type":"reminders","action":"reschedule","reminder_id":"...","when":"tomorrow 09:00"}` | `reminders_rescheduled` |
| details | `{"type":"reminders","action":"details","reminder_id":"..."}` | `reminder_detail` |

Notes:

- Frontend can do **smart mapping** (typed/voice) for phrases like `remind me ...`, `set a reminder ...`, `เตือน...`, `อย่าลืม...` -> `reminders.add`.

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