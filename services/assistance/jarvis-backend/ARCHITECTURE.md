# Jarvis Backend (Index)

This file is intentionally a thin index to reduce staleness.

## Authoritative sources
- Runtime surface area:
  - `GET /agents`
  - `GET /daily-brief`
  - `GET /reminders`
  - `GET /reminders/upcoming`
  - `POST /reminders/{reminder_id}/done`
  - `POST /reminders/{reminder_id}/later`
  - `GET /reminders/{reminder_id}/reschedule/suggest`
  - `POST /reminders/{reminder_id}/reschedule`
  - `GET /debug/agents`
  - `WS /ws/live`
- Agent definitions (the “what”): `agents/*.md`
- Wiring/handlers (the “how”): `main.py`

## Runtime expectations
- Exposes `GET /health`
- Exposes `WS /ws/live`

WebSocket resilience expectation:
- If Gemini Live fails mid-session, the backend should emit an error event and keep the client WebSocket open so deterministic sub-agent handlers can continue.

## Runtime lifecycle (from start)

1) Process boot
- Entry module is `main.py` (FastAPI app + routes + WS endpoint).
- Configuration is loaded from env (see constants at top of file such as `MODEL`, `WEAVIATE_URL`, `SESSION_DB_PATH`, `AGENTS_DIR`).

2) FastAPI startup (`@app.on_event("startup")` -> `_startup`)
- Initializes / migrates the local SQLite session DB:
  - `_init_session_db()`
- If Weaviate is enabled, re-syncs reminders from Weaviate into the local scheduler cache:
  - `_startup_resync_from_weaviate()`
- Starts the reminder scheduler background loop:
  - `asyncio.create_task(_reminder_scheduler_loop())`

3) Reminder scheduler loop (`_reminder_scheduler_loop`)
- Every ~15 seconds:
  - Finds due reminders (`_list_due_reminders(...)`).
  - Marks them fired (`_mark_reminder_fired(...)`).
  - Broadcasts to connected clients:
    - `{ "type": "reminder", "reminder": {...} }`

4) WebSocket session (`WS /ws/live` -> `ws_live`)
- Accepts the client WebSocket.
- Reads session identity from `session_id` query param (provided by the frontend).
- Establishes a Gemini Live session.
- Runs two concurrent loops:
  - `ws_to_gemini`: forwards client audio/text to Gemini when available.
  - `gemini_to_ws`: streams Gemini outputs/tool calls back to the client.
- Deterministic sub-agent handlers (agent triggers) can intercept messages before they reach Gemini.

## Agent system (high-level)
- Agents are defined as Markdown under `agents/*.md`.
- Runtime agent directory is controlled via `JARVIS_AGENTS_DIR` (default `/app/agents`).
- Terminology:
  - Agent: routing/orchestration (trigger phrases, continuation window, status reporting).
  - Skill: deterministic capability (HTTP endpoints / tool calls) invoked by agents or the main LLM session.
- Triggering:
  - The backend builds a trigger map from agent frontmatter `trigger_phrases` (comma-separated string).
  - When a trigger matches, the backend dispatches to a code handler (see `main.py`).
- Continuation window:
  - After a sub-agent handles a message, follow-ups can be routed to the same agent for a short time window.
  - Controlled by `JARVIS_AGENT_CONTINUE_WINDOW_SECONDS` (default `120`).
- Status aggregation:
  - Agents can publish their latest status via `POST /agents/{agent_id}/status`.
  - `GET /daily-brief` aggregates latest status payloads.

## Adding an agent
- Create `agents/<agent-id>.md`.
- Include frontmatter:
  - `id: <agent-id>`
  - `name: ...`
  - `kind: sub_agent|top_level_agent`
  - `trigger_phrases: ...` (optional; comma-separated)
- Implement the handler routing in `main.py`.

Examples:
- `agents/current-news.md` -> handler in `main.py`
- `agents/follow_news.md` -> handler in `main.py`

## Debugging wiring
- Confirm the agent is discovered:
  - `GET /agents`
- Inspect resolved triggers and settings:
  - `GET /debug/agents`
- Confirm triggers are present in the MD frontmatter and match user text.
- Confirm the agent publishes status:
  - `POST /agents/<agent-id>/status`
  - `GET /daily-brief`
- Confirm reminders are visible:
  - `GET /reminders?status=all`
  - `GET /reminders/upcoming?window_hours=48&time_field=notify_at`

## Session state
- Session identity comes from the frontend (`session_id` query param on `WS /ws/live`).
- Session DB is controlled via `JARVIS_SESSION_DB` and should be backed by a volume if persistence is required.

## Guardrails
- Write operations to external systems must be gated behind explicit user confirmation (two-phase propose/commit).

## Key functions in `main.py` (names only)
- `_load_agent_defs`, `_agents_snapshot`
- `_agent_triggers_snapshot`, `_dispatch_sub_agents`
- `_upsert_agent_status`, `_get_agent_statuses`, `_render_daily_brief`
- `_list_reminders`, `_list_upcoming_pending_reminders`
