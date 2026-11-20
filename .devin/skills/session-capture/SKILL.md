---
name: session-capture
description: SSOT-aligned session capture — route knowledge/decisions/requests/outcomes to canonical sinks (session-capture, pointer-note, knowledge-capture).
allowed-tools:
  - exec
  - grep
  - read
  - edit
  - write
  - find_file_by_name
  - todo_write
  - ask_user_question
  - mcp_call_tool
  - mcp_list_tools
triggers:
  - user
  - model
---

Use this skill to auto-capture useful information for later reuse, aligned with SSOT.
Canonical spec: `docs/ssot/ssot.knowledge-capture.yml` (matrix, pointer-note template, triggers, retrieval, guardrails).
Procedures: `knowledge-capture`, `pointer-note`, `session-capture` in `docs/ssot/ssot.procedures.yml`.

## When to run
- **Session end/handoff (mandatory):** run the open-ask sweep before ending.
- **On discovery:** a non-obvious entry point/procedure/lookup path is resolved.
- **On retainable answer:** explainer/comparison/assessment/educate-me worth keeping.
- **On task completion:** reusable deltas or evidence to land.
- **On drift/repeat friction:** stale pointer, repeated lookup, or missing procedure.

## SSOT-first retrieval (do not cache volatile truth)
1. Classify intent (procedure/policy, live state, decision, evidence, how-to).
2. `ada_ssot_search` / `mcp_search_ssot` / `mcp_query_ssot` → identify canonical SSOT key/path (`ssot.index.yml`, `ssot.procedures.yml`, `ssot.registry.yml`, `ssot.file-control.yml`).
3. `ada_ssot_get` / `mcp_read_ssot` / read for stable detail.
4. Consult pointer indexes (knowledge notes, KB, lessons, reports/cards) to jump to canon.
5. Fetch volatile/live state at time of use (board-api, jobs/health/audit/report tools).
6. On conflict, SSOT/designated live authority wins; update/deprecate stale pointers.

## Routing matrix (capture by type)
- **Stable procedure/policy/schema/ownership/quality rule** → SSOT `docs/ssot/**` (validate/register/changelog per `ssot.file-control.yml`); pointer note optional. No parallel truth.
- **Actionable work / follow-up / unmet request** → kanban card/request/comment via board-api (correct write path, `board-write`); focus-inbox only as drop-catcher where appropriate. Board is pending-work truth.
- **Reusable lesson/explainer/assessment/educate-me** → `scripts/lesson-add.py` or `POST /lesson` (board-api) → MDDB `chaba-lessons` (upsert by topic). SSOT keeps verdict/decision + pointer on split. If write fails, say so.
- **Project-local navigation/pointer map/lookup recipe** → pointer-first knowledge note (OpenChamber project knowledge or KB index stub): store refs/paths/keys/queries, not copied bodies/snapshots.
- **Durable repo-local runbook** → `docs/kb/*` (respect writer/role rules); promote to SSOT when normative.
- **Execution evidence/outcomes** → existing evidence surfaces (dispatch outcomes, reports, CI/audit, card result/comms/report). Capture refs/conclusions, not volatile logs without as-of/source.
- **Transient/live operational state** → do not persist as truth; store refresh query/recipe only.

## Session-capture sweep (session end/handoff/pause)
1. **Open-ask sweep:** every unmet/unfinished request or discovered follow-up → card/request/comment, focus-inbox, lesson, KB/SSOT promotion, or pointer note. Record where filed.
2. **Discovery:** create/update a deduped pointer note with `scope, as_of, canonical_refs, retrieval_recipe, volatility, summary` (+ owner/promote_to/related/refresh/gaps).
3. **Lessons:** file retainable answers (lesson-capture duty); state failure explicitly.
4. **Outcomes/evidence:** attach to card/report/artifacts; capture only reusable deltas.
5. **Handoff packet (required):** save a Session Handoff Packet (OpenChamber knowledge note preferred and/or card comms refs) and include it in the response.
6. **Report (mandatory):** always list `where_filed` (`item -> sink/ID/path`) — never end with chat-only outcomes.

## Session Handoff Packet (required)
- `objective` — what this session/task was doing
- `as_of` — YYYY-MM-DD[ HH:MM TZ]
- `current_state` — done | in progress | blocked, with evidence refs
- `canonical_refs` — SSOT keys/paths, card IDs, lesson/report/artifact IDs, commits/paths
- `open_asks_decisions` — none, or each ask/decision -> owner/options/default + durable sink/ID
- `next_action` — single concrete next step
- `where_filed` — **mandatory**: `item -> sink/ID/path`
- `notes` — risks/gaps/refresh queries if any (label state `canonical(served)`, `branch/unmerged`, or `live runtime` when relevant)

## Pointer-note template (body)
- `scope`, `as_of`, `volatility` (static|pointer|live-mix), `owner`, `promote_to`
- **Canonical refs (authoritative):** SSOT/procedure/KB/lesson/report/card refs with why
- **Retrieval recipe:** exact search/get/live queries to refresh
- **Pointer map:** entry point → canonical ref/query
- **Gaps / refresh triggers**

## Guardrails
- Canonicality/freshness: include as-of + refresh; no silent memory-only truth.
- No duplication/secrets: refs/queries only; never copy secrets or volatile dashboards.
- Correct write path/role: board-api mutation door, single-writer/served-checkout/checkout-role rules, field ownership.
- Idempotent/dedupe: upsert/link by stable key (SSOT key, card id, topic slug, artifact/note domain).
- Boundaries: no Ada personal-memory (`ada-*`) writes from Chaba contexts; promote normative changes via governed path.
- On conflict: SSOT/designated live authority wins; correct/deprecate stale pointers.