---
description: Run SSOT-aligned session-capture sweep and produce a handoff packet
---

Run the SSOT-aligned session-capture sweep for this session$ARGUMENTS.

Follow `docs/ssot/ssot.knowledge-capture.yml` and the `session-capture` procedure/skill.

## Sweep (mandatory)
1. **Open-ask:** route every unmet/unfinished request or follow-up to a durable sink and record where filed (a request with no durable record does not exist).
2. **Discovery:** save/update a deduped pointer note (`scope, as_of, canonical_refs, retrieval_recipe, volatility, summary` + owner/promote_to/related/refresh/gaps).
3. **Lessons:** file retainable/educate-me answers (`/lesson` or `scripts/lesson-add.py`); state if write fails.
4. **Focus parity:** log focus decisions/session summaries append-only to `docs/ssot/ssot.focus.decisions.yml` / `docs/ssot/ssot.focus.sessions.yml` (prefer `mcp-debug` `mcp_focus` `session_summary`/`technical_decision`; else consistent append-only edits, never rewrite history).
5. **Evidence:** attach outcomes/evidence to cards/reports; capture only reusable deltas.
6. **Handoff packet (required):** save a Session Handoff Packet (OpenChamber knowledge note preferred and/or card comms refs) and include it in the response.

## Guardrails
- SSOT-first retrieval; SSOT/designated live authority wins on conflict.
- Pointer-first: refs/paths/keys/queries + `as_of`; no copied SSOT bodies, no secrets, no stale volatile snapshots.
- Correct write paths/roles (board-api mutation door, single-writer/checkout rules, field ownership). No Ada `ada-*` memory writes from Chaba contexts.
- Dedupe by stable key. Label state `canonical(served)`, `branch/unmerged`, or `live runtime` when relevant.

## Handoff packet (required fields)
- `objective`, `as_of`
- `current_state` (done | in progress | blocked, with evidence refs)
- `canonical_refs` (SSOT keys/paths, card IDs, lesson/report/artifact IDs, commits/paths)
- `open_asks_decisions` (none, or each -> owner/options/default + durable sink/ID)
- `next_action` (single concrete next step)
- `where_filed` (**mandatory**: `item -> sink/ID/path`)
- `notes` (risks/gaps/refresh queries)

Always report `where_filed` explicitly; never end with chat-only outcomes.
