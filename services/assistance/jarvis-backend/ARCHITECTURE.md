# Jarvis Backend (Index)

This file is intentionally a thin index to reduce staleness.

## Authoritative sources
- Runtime surface area:
  - `GET /agents`
  - `GET /daily-brief`
  - `GET /reminders`
  - `GET /reminders/upcoming`
  - `POST /reminders/{reminder_id}/done`
  - `GET /debug/agents`
  - `WS /ws/live`
- Agent definitions (the “what”): `agents/*.md`
- Wiring/handlers (the “how”): `main.py`

## Runtime expectations
- Exposes `GET /health`
- Exposes `WS /ws/live`

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
