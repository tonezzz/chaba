# SSOT-aligned session capture (knowledge, decisions, requests, outcomes)

Follow `docs/ssot/ssot.knowledge-capture.yml` and procedures `knowledge-capture`, `pointer-note`, `session-capture` in `docs/ssot/ssot.procedures.yml`.

## Defaults
- **SSOT-first retrieval:** `ada_ssot_search`/search → `ada_ssot_get`/read canonical SSOT (`ssot.index.yml`, `ssot.procedures.yml`, `ssot.registry.yml`, `ssot.file-control.yml`) → pointer indexes → fetch volatile state live. SSOT/designated live authority wins on conflict.
- **Pointer-first captures:** store refs/paths/keys/queries + `as_of` and refresh recipe; no copied SSOT bodies, no secrets, no stale volatile snapshots. Dedupe by stable key (SSOT key, card id, topic slug, artifact/note domain).
- **Correct sinks/write paths:** SSOT for stable rules (governed lifecycle); board-api for cards/requests/comments/inbox (board is pending-work truth, respect mutation door/writer/role rules); `/lesson` or `scripts/lesson-add.py` for retainable lessons (upsert, state if write fails); OpenChamber knowledge notes for project pointer maps; `docs/kb/*` or SSOT promotion for durable runbooks; evidence surfaces for outcomes. Never persist live state as truth. No Ada personal-memory (`ada-*`) writes from Chaba contexts.

## Session end/handoff (mandatory sweep)
1. Route every unmet/unfinished request or follow-up to a durable sink and record where filed (open-ask: a request with no durable record does not exist).
2. Save/update a deduped pointer note (scope, as_of, canonical_refs, retrieval_recipe, volatility, summary; owner/promote_to/related/refresh/gaps as needed).
3. File retainable/educate-me answers as lessons.
4. Attach outcomes/evidence to cards/reports; capture only reusable deltas.
5. Save a short resume pointer (state, open asks, next action, where filed).

Use the `session-capture` skill/checklist when available.