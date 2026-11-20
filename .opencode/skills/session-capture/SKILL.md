---
name: session-capture
description: SSOT-aligned capture of knowledge, decisions, requests, and outcomes (session-capture, pointer notes, lessons) for reuse with SSOT-first retrieval.
---

# Session capture (SSOT-aligned)

Apply this skill when ending a session/handoff, after meaningful discovery, when answering retainable questions, or when work produces reusable outcomes.

## Canonical spec
- `docs/ssot/ssot.knowledge-capture.yml` — routing matrix, pointer-note template, triggers, retrieval flow, guardrails
- `docs/ssot/ssot.procedures.yml` — `knowledge-capture`, `pointer-note`, `session-capture`
- `docs/ssot/ssot.file-control.yml` — SSOT lifecycle/governance

## Route by type (canonical sinks)
- **Stable procedure/policy/schema/rule** → SSOT (`docs/ssot/**`, validate/register/changelog)
- **Actionable work/unmet request** → kanban card/request/comment via board-api (focus-inbox only as drop-catcher); board is pending-work truth
- **Retainable lesson/educate-me/assessment** → `/lesson` or `scripts/lesson-add.py` → MDDB `chaba-lessons` (upsert by topic; state if write fails)
- **Project pointer map/lookup recipe** → OpenChamber project knowledge note (pointer-first)
- **Durable runbook** → `docs/kb/*` (promote to SSOT when normative)
- **Evidence/outcomes** → existing evidence surfaces (dispatch/report/CI-audit/card refs)
- **Live/volatile state** → do not persist as truth; store refresh query only

## SSOT-first retrieval
1. `ada_ssot_search`/search → identify canonical SSOT key/path (`ssot.index.yml`, `ssot.procedures.yml`, `ssot.registry.yml`, `ssot.file-control.yml`)
2. `ada_ssot_get`/read for stable detail
3. Use pointer indexes to jump to canon; fetch live state at time of use
4. Conflicts: SSOT or designated live authority wins; fix stale pointers

## Session-end sweep (mandatory)
1. Route every unmet request/follow-up to a durable sink and record where filed
2. Save/update a deduped pointer note: `scope, as_of, canonical_refs, retrieval_recipe, volatility, summary` (+ owner/promote_to/related/refresh/gaps)
3. File retainable lessons (lesson-capture)
4. Attach outcomes/evidence; capture only reusable deltas
5. Save a short resume pointer (state, open asks, next action, where filed)

## Guardrails
- Pointer-first: refs/paths/keys/queries, no copied SSOT bodies, no secrets, no stale volatile snapshots
- Correct write paths/roles (board-api mutation door, single-writer/checkout rules, field ownership)
- Idempotent/dedupe by stable key; governed promotion for normative changes
- No Ada personal-memory (`ada-*`) writes from Chaba contexts
- A request with no durable record does not exist; a lesson that only lived in reply is a miss
