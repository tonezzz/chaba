# Dispatch outcome — ada_memory_search draft 'gap' notes mislead the model as facts

Card: `ada-memory-search-draft-gap-notes-mislea-406683` (ADA-0607) · runner tony-macbook · 2026-10-13

## Finding

Draft surfacing in `ada_memory_search` is **by design** (knowledge-circle loop): `DRAFT_VISIBLE_BANKS={personal,general}` + person-scope banks, gated by `scope==instance`, score ≥0.55, age ≤7d. Hits carry JSON flags `draft:true`/`unverified:true`, and the **bank-recall injection path** already marks them in-band (`[unverified draft]` prefix in `conversation_memory._recall`) — but the **tool-result path** had no in-band marker, so the model read gap-note content as fact despite the flags. Three more leaks found while tracing:

1. `memory_ops._doc_to_hit` — `include_inactive` audit reads returned `status=draft` docs with **no** draft/unverified flag at all.
2. `realtime_provider._note_search_result` — `hits[0].score ≥ 0.6` counts as the "confident hit" that suppresses `ada_session_recall` and grounds the answer; drafts surface at ≥0.55, so a draft could gate out deeper recall.
3. `_dead_turn_fallback` / `_dead_turn_digest` — spoke/quoted `hits[0].content` verbatim with no flag check; a draft top-hit was announced as "found it".

## Changes (this worktree)

- `integrations/ada-pi/backend/tool_runner.memory.draft-hit-frame.patch` — new `DRAFT_HIT_FRAME`/`_frame_draft_hit` (ARCHIVAL_HIT_FRAME pattern): draft hits' content wrapped in `[UNVERIFIED DRAFT — …]` before returning; docstring updated.
- `integrations/ada-pi/backend/memory_ops.draft-include-inactive.patch` — `include_inactive` drafts get `draft`/`unverified` flags → framed like normal drafts.
- `integrations/ada-pi/backend/realtime_provider.draft-hit-gates.patch` — confident gate + dead-turn fallback/digest all filter to verified hits only.
- `integrations/ada-pi/backend/tool_guide.draft-hit-frame.patch` — guide documents the frame.
- `integrations/ada-pi/README.md` — Drop 6 section with install steps + contract.
- `scripts/ada/memory-gap-report.py` — gap-note body self-identifies as DRAFT/unverified (helps any path where content arrives without meta).
- `tests/ada/test_draft_hit_frame.py` — 8 tests: patch-apply+compile vs live ada-pi @1bd0bf2, framed content through the real `MemoryMixin.ada_memory_search` under a stub common, `_doc_to_hit` flag via ast-extract, provider gates via ast-extract. **8/8 pass** (`uvx --with pytest --with pyyaml pytest`).
- `docs/ssot/jobs/ada/2026-10-13-ada-memory-search-draft-gap.yml` — full trail incl. deliberately-not-done (kept draft surfacing; unverified-active framing left as JSON flag; distill drafts untouched).

## NOT deployed

Patches verified `git apply --check` clean vs ada-pi `1bd0bf2`. Install on tony-dell's ada-pi per README drop 6 → `tool-lint` + `pytest` gates → `deploy-ada.sh` + restart ada-ha units — requires explicit approval per deploy policy. `memory-gap-report.py` lands via the normal chaba sync to mn01.

## Verify after deploy

Seed a `status=draft` doc in a personal bank (scope=instance, valid_from=today), run `ada_memory_search` → expect `draft:true` + content starting `[UNVERIFIED DRAFT`. Or watch transcripts for gap notes being hedged instead of stated.
