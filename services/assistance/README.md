# Assistance Services

## System overview

## What this folder is
The `/services/assistance/` tree is the source-of-truth for all *Assistance* application code deployed via the `idc1-assistance` stack.

## Start here
- `CONCEPT.md`
- `services/assistance/docs/CHARTS.md`
- `TOOLS_POLICY.md`
- `MEMORY_POLICY.md`
- Operator playbook (single source of truth): `services/assistance/docs/ACTION.md`
- Build / deploy (single source of truth): `services/assistance/docs/BUILD.md`
- Reminders (overview + data flow): `services/assistance/docs/REMINDERS.md`
- Skills Sheet SSOT routing: `services/assistance/docs/SYSTEM.md`
- Deterministic tools reference: `services/assistance/docs/TOOLS.md`

## Authoritative runtime surfaces (Jarvis)
- Operator note:
  - Treat `services/assistance/docs/ACTION.md` as the operator SSOT for runbooks/checklists.
  - For an authoritative, current API surface, prefer `GET /openapi.json` on the running backend.
- Jarvis Backend:
  - HTTP health: `GET /health`
  - HTTP API surface: `GET /openapi.json`
  - WebSocket: `WS /ws/live`

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
  - `services/assistance/docs/IMAGEN.md`
  - `services/assistance/docs/WEAVIATE.md`
  - `services/assistance/docs/MEMORY.md`
  - `services/assistance/docs/TOOLS.md`
  - `TOKEN_OPTIMIZE.md`

## Memory (current direction)

Hybrid memory model:

- Authoritative store for user-configured memory/knowledge: Google Sheets (see `services/assistance/docs/MEMORY.md`)
- Optional index/cache for search/ranking: Weaviate (internal-only; see `services/assistance/docs/WEAVIATE.md`)
- Operational cache/scheduler: Jarvis backend SQLite (`JARVIS_SESSION_DB`) for reliable reminders

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
  - `JARVIS_REMINDER_TITLE_MODELS` (comma-separated list; tried in order)
  - `JARVIS_REMINDER_TITLE_MODEL` (single model; fallback)
  - `GEMINI_TEXT_MODEL` (single model; fallback)

Reminder title model notes:
- Model names may be provided with or without the `models/` prefix.
- If `JARVIS_REMINDER_TITLE_MODELS` is unset, the backend uses a cheap-first default fallback list.
- If the configured model is unavailable / rate-limited / quota-limited, the backend will try the next model and otherwise keep the original title.

Confirmed available model IDs (via Gemini API `models.list()` from the running `jarvis-backend` container):
- `models/gemini-2.0-flash-lite`
- `models/gemini-2.0-flash-lite-001`
- `models/gemini-2.0-flash`
- `models/gemini-2.0-flash-001`
- `models/gemini-flash-lite-latest`
- `models/gemini-flash-latest`
- `models/gemini-pro-latest`

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
  - `/stacks/idc1-assistance-*` (4-stack split: infra, mcp, core, workers)

Operational note:
- `idc1-assistance` is deployed as **Portainer git-backed stacks** (4 separate stacks).
- **Portainer is authoritative for:**
  - Stack file content it deploys
  - Stack environment variables (secrets like OAuth client IDs)
- **Git is authoritative for:**
  - Compose structure and service definitions
  - Default env var values (via `env:` in compose)

### Deploy Commands

**Full hands-off deploy (recommended):**
```bash
./scripts/deploy-idc1-assistance.sh
```

**Check env drift only:**
```bash
./scripts/deploy-idc1-assistance.sh --check-env
```

**Manual redeploy with Portainer env:**
```bash
# Export Portainer env vars first
eval $(curl -s "http://127.0.0.1:9000/api/stacks/80" \
  -H "X-API-Key: $PORTAINER_TOKEN" | \
  jq -r '.Env[] | "export \(.name)=\(.value|@sh)"' | \
  grep -vE "SECRET|TOKEN|API_KEY|CLIENT_SECRET")

# Then redeploy
docker compose -f stacks/idc1-assistance-core/docker-compose.yml up -d
```

### Common Trap
Running `docker compose ... up` locally without exporting Portainer env first creates containers that **look** correct but **do not include** Portainer stack env (secrets, feature flags). This leads to confusing failures like:
- `missing_google_tasks_client_id`
- Agents loading when `JARVIS_SKIP_AGENTS=1` was set in Portainer
- Wrong STT model being used

Always use the deploy script or export Portainer env first.
