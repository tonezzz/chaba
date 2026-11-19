# Dispatch outcome — merge-sweep-test-gate-fail-open (OPS-1191)

## Summary

Implemented the card's option 1 (fail-closed), extended with the card-discussion direction (repo-scoped pytest bootstrap) plus a `pytest` claim label for re-routing retries: `scripts/board/dispatch_repos.py` now treats an unrunnable test gate — pytest-shaped command, tests/ present, no importable pytest anywhere — as a merge blocker (`gate_unrunnable`) instead of the 2026-11-08 fail-open, first attempting a bounded, locked bootstrap of the canonical checkout's `.venv` with the repo's declared deps (`KANBAN_GATE_BOOTSTRAP=0` opts out); `action.test_exempt` is the allowlist for docs-only work; `merge-sweep.py` runs the same baseline-aware gate inside `merge_strict` before push and stamps held heads under `action.sweep.gate_blocked` so a pytest-less runner can no longer strand its branch into an ungated sweep merge; and both `kanban-dispatch.py` and `runner-agent.py` auto-advertise the `pytest` label from `dr.pytest_capable()`, with unrunnable requeues gaining `labels:[pytest]` so retries only land where the gate can run. Tests: `test_dispatch_close_out.py` 48 pass, `test_merge_sweep.py` 44 pass, full merge-gate smoke set 139 pass (231 total). Verify: `python3 -m pytest tests/board/test_dispatch_close_out.py tests/board/test_merge_sweep.py -x -q`.

## What changed

- `scripts/board/dispatch_repos.py`
  - `run_test_gate`: unrunnable = fail-closed (`{ok: False, unrunnable}`); `action.test_exempt` skip; `'command not found'`/`No module named` output on any gate command now holds too.
  - `_bootstrap_gate_python` / `gate_bootstrap_needed`: provisions `<checkout>/.venv` (or tops up an existing `venv/`) with `REPO_TESTS[repo]['bootstrap']` deps (chaba: `[pytest, pyyaml]`); flock-serialized, 6h retry stamp, `KANBAN_GATE_BOOTSTRAP` env gate.
  - `pytest_capable()`: probe used by the label auto-advertise — True only for a proven importable interpreter (system python3 or a repos.conf checkout venv); bootstrap provisionability doesn't count.
  - `REPO_TESTS` schema gained `bootstrap:`; chaba entry declares `[pytest, pyyaml]`.
  - `baseline_aware_test_gate`, `_merge_and_gate`, `close_out`, `close_out_notes` plumb `card` through and surface `gate_unrunnable` distinctly from `test_failures`.
- `scripts/board/merge-sweep.py`
  - `merge_strict(repo, sha, base_ref, base, repo_name, card)` runs `dr.baseline_aware_test_gate` on the merged worktree before push; unrunnable → `gate_unrunnable`, red → `test_failures`, green → merges and returns the gate result in `tests`.
  - `sweep_card` stamps `action.sweep.gate_blocked` (head[:12]-keyed) on held heads, skips re-testing the same blocked head, re-gates on a new head, and appends gate evidence (`test gate passed Ns` / `skipped: reason`) to merged comms.
- `scripts/board/kanban-dispatch.py` — `MY_LABELS` auto-adds `pytest` when `dr.pytest_capable()`; the auto-requeue path adds `labels:[pytest]` to cards requeued via `gate_unrunnable`.
- `scripts/board/runner-agent.py` — same `pytest` auto-advertise for `LABELS`; `close_out` treats `gate_unrunnable` as a non-merge result (card stays, reported).
- `docs/ssot/kanban/ssot.kanban.yml` — step-5 gate prose rewritten for fail-closed + bootstrap + label; `action.test_exempt` documented; `labels`/`runner_fleet` notes on the auto-advertised `pytest` label.
- `docs/ssot/jobs/kanban/2026-11-19-merge-test-gate-fail-closed.yml` — runbook (decision, behavior, ops/redeploy notes, edge cases).
- Tests — `test_dispatch_close_out.py`: fail-open test replaced by fail-closed, plus missing-pytest interpreter test and test_exempt merge test; fixtures force `KANBAN_GATE_BOOTSTRAP=0` (bootstrap tests opt back in). `test_merge_sweep.py`: new gate tests (unrunnable holds + stamps + no repeat note, new failure holds, green merges with comms evidence).

## Result

Pass — 231 board tests green (48 + 44 + 139 smoke). Behavior: a merge now reaches origin only with real test evidence, an explicit `test_exempt` mark, or a declared skip (no tests dir / rc 5 / `KANBAN_TESTGATE=0`); unrunnable hosts hold and route the retry to pytest-capable runners.

## How to verify

- `python3 -m pytest tests/board/test_dispatch_close_out.py tests/board/test_merge_sweep.py -x -q`
- On a pytest-less host: chaba dispatch merge holds with "test gate could not run — merge held (fail-closed)", card requeues with `labels:[pytest]`; or the host's canonical checkout gains `.venv/bin/pytest` via the bootstrap.
- Ops follow-up (not this session): redeploy `runner-agent.py` to fleet hosts so the `pytest` auto-advertise is live everywhere.

lessons:
- merge-sweep must carry gate results through `merge_strict`'s return — `tests` key on success — or comms can't report the evidence and tests asserting it fail.
- Repo-scoped bootstrap must be opt-out in test fixtures (`KANBAN_GATE_BOOTSTRAP=0`) or hermetic tests fire real venv/pip; bootstrap tests then opt back in explicitly.
- Capability labels need a probe, not a declaration — `pytest_capable()` only counts an interpreter that can actually import pytest; "could bootstrap one" would re-admit the failure mode.
- A head-keyed block stamp (`action.sweep.gate_blocked`) stops 15-min sweeps from re-running an expensive failing gate and re-posting identical comms.
