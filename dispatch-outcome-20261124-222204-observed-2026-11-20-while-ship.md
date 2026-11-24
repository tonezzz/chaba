# Dispatch outcome — board-tests-control-pane-lane-failures

## Result: DONE — tests/board passes clean on pristine origin/master worktree

Commit `36f762530c` on `dispatch/20261124-222204-observed-2026-11-20-while-ship`
(3 files, +110/-1). No push, no deploy.

## What was actually wrong

The 6 failures named in the card were **already fixed on master** before
this dispatch ran:

- `test_runner_agent_lane.py::ClaimPassLaneTest` (3 tests) — fixed by the
  lane-provenance/hermetic commits (`33553f1168`, `a84dab8234`).
- `test_control_pane_projection.py` card-record tests (2 of 3) — fixed by
  `9ec3614046` (archive-aware KNB-0229 card path, landed 2026-11-24).

The failures that DO reproduce on a pristine origin/master worktree today
are different and environmental:

1. **`test_pane_implemented_on_board_page` + `test_pane_data_contract_on_board_payload`**
   read `stacks/web/public/apps/board2/{index.html,cards.json}` — gitignored
   `render-board2.py` outputs absent on any pristine checkout
   (FileNotFoundError). The 2026-11-20 observation ran where the render had
   already happened.

2. **6 `test_dispatch_close_out.py::Case` tests** exercise `close_out`'s
   real `REPO_TESTS["chaba"]` merge gate, which resolves a pytest-capable
   interpreter via `<wt>/.venv` → `<repo-root>/.venv` → `<repos.conf>/.venv`
   → system `python3` (`dispatch_repos.py gate_python`). On tony-macbook,
   `python3` (3.14) has no pytest and `~/CascadeProjects/chaba` has no
   `.venv`, so the gate went unrunnable (OPS-1191 fail-closed) and held
   every merge → `assertTrue(res["merged"])` failed.

## Fix (correct side — tests were under-specified, not the behavior)

- `tests/board/test_control_pane_projection.py`: module-scoped autouse
  fixture renders `scripts/render-board2.py` once when the outputs are
  missing. **Asserts untouched** — they still validate the real generated
  payload; the fixture only guarantees the input exists. Plain render (no
  `--if-changed`) so tracked `.render-state-board2` is not mutated.
- `tests/board/test_dispatch_close_out.py` `Case.setUp`: plants a
  `sys.executable` shim at `<main>/.venv/bin/python` so `gate_python`
  resolves a pytest-capable interpreter hermetically on any host.
- `test_gate_venv_python_unholds_merge`: shadows the setUp shim with a
  pytest-less venv before its no-venv-resolvable phase (its subject IS the
  system-python3 fallback).
- `test_gate_skips_venv_without_pytest`: gains the file's existing
  `skipUnless(python3 imports pytest)` guard — its contract requires a
  pytest-capable system python3. Asserts unchanged.

## Verified

- `pytest tests/board/test_control_pane_projection.py
  tests/board/test_dispatch_close_out.py` with board2 outputs deleted
  (pristine simulation): **53 passed, 7 skipped**.
- Under a pytest-capable `python3` PATH shim, all 7 pytest-dependent
  tests run green (incl. `test_gate_venv_python_unholds_merge` and
  `test_gate_skips_venv_without_pytest`).
- **Full `pytest tests/board`: 1005 passed, 7 skipped, 17 subtests
  passed, 0 failed** (~11.7 min).
- Pristine re-check: deleted `board2/` again → fixture re-rendered →
  7/7 pass; `git status` clean of generated artifacts.

Trail: `docs/ssot/jobs/board/2026-11-24-board-tests-hermetic-gate-render.yml`.

## Follow-up (host, not repo)

tony-macbook lacks pytest for system python3 — the dispatch merge gate
itself is unrunnable here per OPS-1191. Install `python3-pytest` on
dispatch-capable hosts or keep test-gated merges on pytest-capable hosts.

lessons:
- tests/board tests that read `stacks/web/public/apps/board2/*` depend on gitignored render outputs — a module fixture running `scripts/render-board2.py` when missing makes them pristine-safe (plain render; `--if-changed` would dirty tracked `.render-state-board2`).
- `test_dispatch_close_out.py::Case` exercises the REAL `REPO_TESTS["chaba"]` gate — it needs a pytest-capable interpreter resolvable via checkout `.venv`; a `sys.executable` shim venv in the fixture's canonical checkout makes it hermetic, but tests whose subject IS system-python3 fallback still need the file's `skipUnless(python3 -c "import pytest")` guard.
- The 6 card-listed failures were already fixed on master — always re-run the named tests on current origin/master before assuming the card's failure list is current.
