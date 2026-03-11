# Assistance Services

## What this folder is
The `/services/assistance/` tree is the source-of-truth for all *Assistance* application code deployed via the `idc1-assistance` stack.

## Start here
- `CONCEPT.md`
- `TOOLS_POLICY.md`
- `MEMORY_POLICY.md`
- Build / deploy (single source of truth): `docs/BUILD.md`
- Reminders (overview + data flow): `docs/REMINDERS.md`

## Authoritative runtime surfaces (Jarvis)
- Jarvis Backend (HTTP):
  - `GET /health`
  - `GET /agents`
  - `GET /debug/agents`
  - `GET /daily-brief`
  - `GET /reminders`
  - `GET /reminders/upcoming`
  - `POST /reminders/{reminder_id}/done`
  - `POST /reminders/{reminder_id}/later`
  - `GET /reminders/{reminder_id}/reschedule/suggest`
  - `POST /reminders/{reminder_id}/reschedule`
- Jarvis Backend (WebSocket):
  - `WS /ws/live`

Troubleshooting:
- If the UI disconnects immediately after clicking Initialize, check `jarvis-backend` logs for Gemini Live connection errors (and ensure Portainer actually pulled the latest image digest on redeploy).
- If Gemini Live fails mid-session, the backend should keep the client WebSocket open and emit an error event (see `services/assistance/DEBUG.md`).
  - If the error event is `gemini_live_model_not_found`, check `GEMINI_LIVE_MODEL` and ensure your API key has access to that model.

## Agents
- Agent definitions live under:
  - `jarvis-backend/agents/*.md`
- Trigger wiring and handlers live in:
  - `jarvis-backend/main.py`

Notable sub-agents:
- `reminder-setup`: deterministic reminder creation via chat messages like `reminder setup: ...`
- `reminder-helper`: fast reminder CRUD helper (add/list/done/later/reschedule/delete)
- `follow_news`: configurable news-follow workflow (focus list, refresh, stored summaries)

Terminology:
- **Agent**: a conversation-aware routing/orchestration module (trigger phrases, continuation window, status reporting).
- **Skill**: a deterministic capability invoked by agents or the main LLM session (HTTP endpoints / tool calls).

### Sub-agents (mechanism)

In this codebase, a "sub-agent" is not a separate continuously-running model.
It is a backend routing mechanism that can intercept user input and run a dedicated handler.

High-level flow:
1. The frontend sends user input to the backend over `WS /ws/live`.
2. The backend tries to dispatch the message to a sub-agent based on:
   - trigger phrase matches from `jarvis-backend/agents/*.md`, or
   - an active-agent continuation window (recent agent stays active for follow-ups).
3. If dispatched, the backend calls a Python handler in `main.py` (for example, the reminder setup handler).
4. The handler performs deterministic work (e.g. parse time, write SQLite, write-through to Weaviate) and emits WebSocket events for the UI.
5. If not dispatched, the backend forwards the message to the main LLM session (Gemini) and may receive tool calls.

### Sub-agent: follow_news (Follow News / ติดตามข่าว)

Purpose:
- Track user-defined news focus topics across multiple RSS sources, store summaries, and let the user choose which summary to report.

Common commands:
- `follow news` / `ติดตามข่าว`
- `follow news refresh` / `ติดตามข่าว รีเฟรช`
- `focus list` / `โฟกัสข่าว`
- `focus add: <topic>` / `โฟกัสข่าว เพิ่ม: <หัวข้อ>`
- `focus remove: <topic>` / `โฟกัสข่าว ลบ: <หัวข้อ>`
- `report: <summary_id>` / `รายงานข่าว: <summary_id>`

How this is more advanced than a plain backend "skill":
- **Conversation-aware routing**: supports trigger phrases plus a continuation window so follow-up messages can stay within the same intent.
- **WebSocket-first UX**: handlers can emit structured events for lifecycle updates (e.g. reminder created/fired) without waiting for an LLM response.
- **Hybrid with tool calls**: reminders can also be created via LLM tool calls; the sub-agent path is a backend-first fast path.
- **Separation of concerns**: agent definition is data-driven (`*.md`), while handler logic remains in code.

## Service docs
- `jarvis-backend/ARCHITECTURE.md`
- `jarvis-frontend/ARCHITECTURE.md`
- `trip/ARCHITECTURE.md`
- `mcp-servers/ARCHITECTURE.md`
- Ground truth specs:
  - `docs/IMAGEN.md`
  - `docs/WEAVIATE.md`
  - `TOKEN_OPTIMIZE.md`

## Memory (current direction)
- Authoritative store: Weaviate (internal-only container in the `idc1-assistance` stack)
- Operational cache/scheduler: Jarvis backend SQLite (`JARVIS_SESSION_DB`)

Reminder semantics (current direction):
- Weaviate is the authoritative source for reminder retrieval (cross-device consistency).
- SQLite is a local scheduler cache that should be hydrated from Weaviate on startup/reconnect.
- Reminders should support multiple distinct tasks at the same time (e.g. job1 9:00am + job2 9:00am).
- Reminder lifecycle includes a completion state: `done` (completed reminders should disappear from "today" views).

Reminder visibility:
- Reminders can be temporarily hidden via `hide_until` ("Later") to keep Today views manageable.
- Default lists exclude hidden reminders.
- To include hidden reminders:
  - `GET /reminders?include_hidden=true`

Unscheduled reminders:
- `notify_at` can be null for "no time set" reminders.
- These reminders remain `pending` but will not appear in upcoming-notification lists until scheduled.

Reminder title quality:
- The backend can optionally rewrite reminder titles to be clearer before creating the reminder (best-effort; falls back safely).
- Configure the text model via:
  - `JARVIS_REMINDER_TITLE_MODEL` (preferred)
  - `GEMINI_TEXT_MODEL` (fallback)

SQLite schema migration note:
- If `JARVIS_SESSION_DB` is persisted from older deployments, the backend may need to migrate the `reminders` table to add new columns (e.g. `hide_until`).
- If you see errors like `no such column: hide_until`, redeploy an image that includes the migration logic and confirm the DB path is writable.

Reminder tools (Gemini Live function calls):
- `reminders_list`, `reminders_upcoming`, `reminders_done` are implemented in the Jarvis backend (not in 1MCP).
- If `JARVIS_TOOL_ALLOWLIST` is set, ensure it includes these names or the model will not be able to call them.

Time tool (Gemini Live function call):
- `time_now` returns authoritative server time in UTC and the user timezone (see `local_iso`, `utc_iso`, `unix_ts`).

## Deep research

The stack includes an optional `deep-research-worker` service used by the `deep-research` agent/handler in `jarvis-backend/main.py`.
The backend calls the worker over HTTP (configured by `DEEP_RESEARCH_WORKER_BASE_URL`).

Persistence:
- The worker stores job state in SQLite at `DEEP_RESEARCH_DB` (stack default: `/data/deep_research.sqlite`).
- The `/data` mount must be writable by the worker process (runs as a non-root user in the container).

## MCP image pipeline

The stack runs `mcp-image-pipeline` (1MCP) as a separate HTTP MCP gateway.

Troubleshooting:
- If image generation returns `RESOURCE_EXHAUSTED` / `Quota exceeded` (429), it is usually a quota/billing issue for the configured Gemini image model.
- If it returns auth errors (401/403), confirm `GEMINI_API_KEY` is set for the service.

Healthcheck note:
- Container healthchecks should not assume `curl` exists; use `wget` or a similar minimal tool.

## Deployment
- Stack configuration lives under:
  - `/stacks/idc1-assistance/`
