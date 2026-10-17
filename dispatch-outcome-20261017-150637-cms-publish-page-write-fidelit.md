# cms_publish_page write fidelity — stored content diverged from narrated content

Card: `ada-cms-write-fidelity` (ADA-0732) · 2026-10-17 · tony-macbook

## Root cause (answered)

**Model slip, not tool mangling.** Read the full write path on ada-voice
`a9a8cca`: `cms_publish_page` in `backend/tool_runner/cms.py` passes the
`content` arg verbatim to `mddb_client.add_document` → `POST /add
{contentMd}` — no transform anywhere (slug/lang normalization and the
confirm gate never touch content). The kk-cms-only bench divergence
('Tuesdays' stored while 'Mondays' narrated) is therefore in the
generation itself: narration and tool args are separate model outputs
that nothing binds — the same failure class as phantom `ok:true`, but
persisted.

## What shipped — ada-voice Drop 13 (staged, not deployed)

- `integrations/ada-voice/backend/write-fidelity.patch` (272 lines,
  applies clean vs a9a8cca AND the live tony-macbook checkout):
  1. `backend/tool_runner/cms.py` — post-write read-back: after
     `add_document` succeeds, the doc is re-read; the result gains
     `stored_verified` (true/false/"unknown"), `stored_sha256`,
     `stored_excerpt` + a note directing the model to republish if any
     stored fact differs from what she told the user.
  2. `backend/realtime_provider.py` — `write_fidelity` ops event:
     `_fidelity_tokens` extracts weekday/clock-time/date sets (en+th in
     one normalized space) from the assistant narration AND the last-3
     user turns; a published call whose persisted `content` arg
     CONTRADICTS them (both sets non-empty, disjoint) emits an advisory
     event at the final segment boundary — session-audit/QC sees it.
     Vague narration can't flag (contradiction-only).
  3. `tests/scenarios-live/kk_cms_only_seeded_recall.yaml` — turn 2
     pins `calls_any: [cms_publish_page]` and asserts
     `call_args_contain` for the seeded facts (Monday/Thursday/prime,
     en+th alternates) — the deterministic bench catch that would have
     failed the original run.
- `integrations/ada-voice/tests/test_write_fidelity.py` — 17 unit
  tests (staged copy for ada-voice `tests/`).
- `tests/ada/test_write_fidelity_drop.py` — chaba-side drop guard: 6
  tests covering patch content markers, staged-test compile, README/job
  records, and tri-state apply vs the real checkout (via `_drops`).
- `docs/ssot/jobs/ada/2026-10-17-cms-write-fidelity.yml` — job record.
- `integrations/ada-voice/README.md` — Drop 13 install/verified docs.

## Verification

- `tests/test_write_fidelity.py` 17/17 green (bare uv venv).
- ada-voice regression: `test_cms_regen + test_dead_turn +
  test_alias_hit_report + test_memory_pending` = 71 passed.
  `test_tool_runner` = 260 passed + 1 failure
  (`test_non_dict_return_wraps_in_output`) that reproduces on CLEAN
  HEAD — pre-existing, unrelated.
- `tool-lint` clean; `scenario-schema-check` 196 files 0 violations;
  `git apply --check` clean.
- chaba-side: `tests/ada/test_write_fidelity_drop.py` 6/6 green
  (patch state vs live checkout = applies).
- NOT verified live: no real mddb from here — first real publish on a
  dev lane exercises the read-back end to end.

## To install

Per README Drop 13: `git apply` the patch in an ada-voice worktree +
copy the test file, then run the deploy gates. Do NOT deploy from here.
