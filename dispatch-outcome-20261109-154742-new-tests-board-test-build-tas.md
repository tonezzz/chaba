# dispatch-outcome: build_task regression harness

Card: dispatch-prompt-regression-harness (KNB-1276)
Runner: idc02 — branch dispatch/20261109-154742-new-tests-board-test-build-tas

## What changed

New `tests/board/test_build_task_regressions.py` — 7 unittest-style
tests (same importlib-via-spec_from_file_location conventions as
test_lesson_primer.py / test_kanban_dispatch_rails.py) pinning
`scripts/board/kanban-dispatch.py::build_task`'s prompt contract:

1. spec card → spec verbatim precedes TASK_RAILS; `{id}`/`{api}`
   substituted, no placeholders left.
2. retry card (`action.attempts=1`, `last_failure='boom'`) →
   RETRY_RAILS with "This is attempt 2" + failure text; absent fresh.
3. `report: <slug>` card → REPORT_RAILS with slug; absent otherwise.
4. spec-less card → title+note fallback, no crash.
5. `KANBAN_PRIMER=0` → no KNOWN_PITFALLS block even when lp.build has
   lines (lp.build asserted never called).
6. primer-on (lp.build mocked to 8 lines) → KNOWN_PITFALLS ordered
   after TASK_RAILS, before RETRY_RAILS and REPORT_RAILS; <=8 bullets.
7. byte tripwire: rendered TASK_RAILS+RETRY_RAILS+REPORT_RAILS <=
   `FIXED_RAIL_BUDGET_BYTES = 6000` — module-top constant commented
   "rail accretion tripwire — raise only deliberately"
   (current fixed overhead: ~2.8 KB).

No `test_prompt_budget.py` — everything folded into the one file as
the card preferred. No production code touched.

Gotcha encoded in the test: TASK_RAILS itself says "KNOWN_PITFALLS"
(outcome-doc instructions), so block-presence checks key on the unique
marker `"KNOWN_PITFALLS — lessons harvested"` (PRIMER_MARK), not the
bare word — a naive `assertNotIn("KNOWN_PITFALLS")` always fails.

## Result / verification

- `pytest tests/board/test_build_task_regressions.py` → 7/7 green.
- `pytest tests/board` → 470 passed, 6 skipped (one flaky
  test_single_card_404 socket timeout seen once under suite load;
  green on rerun — pre-existing flake, not this change).
- `pytest tests` (full suite, 1411 collected) → no import side-effects
  from the lp monkeypatch (mock.patch.object auto-restores;
  test_lesson_primer exercises real lp and stays green). 3 pre-existing
  environmental failures unrelated to this change:
  - tests/ada/test_correction_command.py — ada-voice checkout's
    .venv/bin/python has no pytest on this host.
  - tests/ada/test_write_fidelity_drop.py — write-fidelity.patch
    diverged vs the live ada-voice checkout (world state).
  - tests/test_ada_ha_cline_dashboard.py — script raises "no
    Kanban/Board view", test regex expects "no Board view"
    (message drift predating this branch).
  - Also: fresh-env runs need `httpx` + `Pillow` for tests/ada +
    tests/ops collection (installed in the throwaway venv only).

Verify: `python3 -m pytest tests/board -x -q` on any pytest-capable
interpreter (this host needed a `/tmp` venv — system python3 has no
pytest, matching the merge gate's fail-open convention).

lessons:
- TASK_RAILS itself contains the word KNOWN_PITFALLS — primer-block
  assertions must match the block's marker text, not the bare word.
- On idc02, system python3 has no pytest and no pip — spawn a
  `python3 -m venv --system-site-packages /tmp/venv` (keeps yaml et al)
  and pip-install pytest there.
