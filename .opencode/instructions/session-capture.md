# SSOT-aligned session capture (knowledge, decisions, requests, outcomes)

Follow `docs/ssot/ssot.knowledge-capture.yml` and procedures `knowledge-capture`, `pointer-note`, `session-capture` in `docs/ssot/ssot.procedures.yml`. **Enforced routine: run the session-capture sweep and produce a handoff packet at every session end, handoff, or pause.**

## Defaults
- **SSOT-first retrieval:** `ada_ssot_search`/search → `ada_ssot_get`/read canonical SSOT (`ssot.index.yml`, `ssot.procedures.yml`, `ssot.registry.yml`, `ssot.file-control.yml`) → pointer indexes → fetch volatile state live. SSOT/designated live authority wins on conflict.
- **Pointer-first captures:** store refs/paths/keys/queries + `as_of` and refresh recipe; no copied SSOT bodies, no secrets, no stale volatile snapshots. Dedupe by stable key (SSOT key, card id, topic slug, artifact/note domain).
- **Correct sinks/write paths:** SSOT for stable rules (governed lifecycle); board-api for cards/requests/comments/inbox (board is pending-work truth, respect mutation door/writer/role rules); `/lesson` or `scripts/lesson-add.py` for retainable lessons (upsert, state if write fails); OpenChamber knowledge notes for project pointer maps; `docs/kb/*` or SSOT promotion for durable runbooks; evidence surfaces for outcomes. Never persist live state as truth. No Ada personal-memory (`ada-*`) writes from Chaba contexts.
- **Label state clearly:** mark facts as `canonical(served)`, `branch/unmerged`, or `live runtime` when relevant.

## Session-capture sweep (mandatory at end/handoff/pause)
1. **Open-ask:** route every unmet/unfinished request or follow-up to a durable sink and record where filed (a request with no durable record does not exist).
2. **Discovery:** save/update a deduped pointer note (`scope, as_of, canonical_refs, retrieval_recipe, volatility, summary` + owner/promote_to/related/refresh/gaps as needed).
3. **Lessons:** file retainable/educate-me answers (state if write fails — a lesson only in reply is a miss).
4. **Focus parity:** log focus decisions/session summaries append-only to `docs/ssot/ssot.focus.decisions.yml` / `docs/ssot/ssot.focus.sessions.yml`. Prefer `mcp-debug` `mcp_focus` (`session_summary` / `technical_decision`; recommend/status also log decisions) where available; otherwise make consistent append-only edits preserving required fields and never rewriting history.
5. **Evidence:** attach outcomes/evidence to cards/reports; capture only reusable deltas.
6. **Handoff packet (required):** save a Session Handoff Packet (OpenChamber knowledge note preferred and/or card comms refs) and include it in the response.
7. **Router event (dry-run):** emit one idempotent capture-router event for the packet via `python3 scripts/chaba/capture-event.py --type handoff --source opencode --session <id> --subject <packet-id> --summary "..." --ref <sink ref> --where-filed "<item -> sink>"` — dry-run only, dedupes by `dedupe_key`, refuses evidence-free handoffs, never writes canonical sinks.

Where available (Chaba pipeline), `scripts/chaba/immediate-pin.py` and `scripts/chaba/recent-event.py` may record structured resume/events, but they do **not** replace durable sinks or the handoff packet.

## Session Handoff Packet (required fields)
- `objective` — what this session/task was doing
- `as_of` — YYYY-MM-DD[ HH:MM TZ]
- `current_state` — done | in progress | blocked, with evidence refs
- `canonical_refs` — SSOT keys/paths, card IDs, lesson/report/artifact IDs, commits/paths
- `open_asks_decisions` — none, or each ask/decision -> owner/options/default + durable sink/ID
- `next_action` — single concrete next step
- `where_filed` — **mandatory** list: `item -> sink/ID/path` (include "none" only if truly nothing captured)
- `notes` — risks/gaps/refresh queries if any

**Response rule:** always report `where_filed` explicitly; never end with chat-only outcomes.

Use the `session-capture` skill/checklist when available.