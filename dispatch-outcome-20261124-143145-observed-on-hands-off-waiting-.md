# Dispatch outcome — merge-sweep-test-gate-fail-open (OPS-1191), attempt 3

## Summary

Re-landed the approved fail-closed merge test gate by merging the
still-unlanded attempt-2 branch
`origin/dispatch/20261119-165806-observed-on-hands-off-waiting-` onto
current master — no re-implementation needed; the work was correct, it
just never got merged (verify-fail 2026-11-23: `gate_unrunnable` absent
from origin/master). Two conflicts resolved: `_merge_and_gate` now keeps
 BOTH the card-aware `baseline_aware_test_gate(..., card)` call AND
master's newer docs-only timeout-override; `ssot.dev-system.assessment.yml`
 churn from the old branch was excluded (took master's newer snapshot).

Decision (unchanged, Tony-approved 2026-11-19): **fail-closed** —
`run_test_gate` returns `unrunnable` (ok=False) when a pytest-shaped gate
has tests/ present but no interpreter can `import pytest` after venv
resolution + a bounded repo-scoped bootstrap
(`_bootstrap_gate_python` provisions the canonical checkout's venv with
`REPO_TESTS[repo]['bootstrap']` — chaba: `[pytest, pyyaml]`, never a
global install). `action.test_exempt` is the docs-only allowlist.
Unrunnable requeues gain `labels:[pytest]`; runner-agent and
kanban-dispatch auto-advertise `pytest` when `dr.pytest_capable()`
proves an interpreter. merge-sweep's `merge_strict` now runs the same
baseline-aware gate before push (previously ungated — the actual
fail-open hole) with head-keyed `sweep.gate_blocked` stamps.

Why prior attempts held: the merge gate always runs the PRE-merge
master's `dispatch_repos` (imported from the host's exec checkout,
hourly-synced) — a branch cannot widen its own gate's timeout. Attempt
2's 240s→900s bump only helps merges AFTER it lands. Re-measured the
chaba 12-file gate set on tony-omen today: **247 tests / ~78s** — the
earlier ~483s was a loaded-host outlier, so this merge clears the old
240s budget comfortably; 900s stays as headroom for loaded idc03.

## What changed (net vs master)

- `scripts/board/dispatch_repos.py` — fail-closed `unrunnable` gate,
  `_bootstrap_gate_python` + `pytest_capable()`, `action.test_exempt`,
  `card` plumbed through `baseline_aware_test_gate`/`_merge_and_gate`/
  `close_out`/`close_out_notes`, chaba gate timeout 240→900 + bootstrap
  deps. Merged with master's TEST_TIMEOUT_RETRIES loop and
  docs-only `timeout_override` intact.
- `scripts/board/merge-sweep.py` — `merge_strict` runs the gate
  pre-push; `gate_unrunnable`/`test_failures` hold with `gate_blocked`
  stamp; merged comms carry gate evidence.
- `scripts/board/kanban-dispatch.py` — `pytest` auto-label;
  unrunnable requeue pins `labels:[pytest]`.
- `scripts/board/runner-agent.py` — `pytest` auto-advertise;
  `gate_unrunnable` counted as a non-merge result.
- `docs/ssot/kanban/ssot.kanban.yml` — schema/execution prose.
- `docs/ssot/jobs/kanban/2026-11-19-merge-test-gate-fail-closed.yml` —
  runbook, now with a `landings:` trail for all three attempts.
- `tests/board/test_dispatch_close_out.py` + `test_merge_sweep.py` —
  fail-open tests replaced by fail-closed coverage (unrunnable hold,
  test_exempt pass, bootstrap stamp/venv reuse, sweep-side gate).
- Prior attempts' per-session outcome docs carried along.

## Result

Pass locally — `test_dispatch_close_out.py` + `test_merge_sweep.py`
101/101 green; full 12-file chaba gate set 247/247 in ~78s on tony-omen.
Operational follow-through (not code): once merged, the served checkout
on idc03 picks up merge-sweep/dispatch_repos via kanban-commit pull;
`runner-agent.py` still needs its routine fleet redeploy for the `pytest`
label auto-advertise (fleet drift notes already on the card). Until then
a `labels:[pytest]` card may starve into the unclaimable warn — intended
honest pressure, per the runbook.

## How to verify

- `python3 -m pytest tests/board/test_dispatch_close_out.py tests/board/test_merge_sweep.py -x -q`
- `python3 -c "import sys; sys.path.insert(0,'scripts/board'); import dispatch_repos as dr; print(dr.test_gate_config('chaba'))"` → `timeout: 900`, `bootstrap: [pytest, pyyaml]`
- `grep -n unrunnable scripts/board/dispatch_repos.py` → present on master post-merge.
- On a pytest-less host: merge holds with "test gate could not run —
  merge held (fail-closed)"; card requeues with `labels:[pytest]`.

lessons:
- A dispatch branch can never fix the gate that evaluates its own merge — the gate runs the pre-merge master's dispatch_repos from the host exec checkout. Timeout/config bumps only help FUTURE merges; this card needed three attempts because attempts 1-2 held on the old 240s budget.
- Re-landing a pushed-but-unmerged dispatch branch beats re-implementing: check `git branch -r` for prior attempt branches first; merge it and resolve only the real conflicts.
- Merge auto-resolution can silently drop EITHER side of an overlapping feature — always re-read the conflicted hunks AND the auto-merged neighbors (here: master's docs-only timeout_override vs the branch's card-aware gate call).
- Auto-generated churn files (ssot.dev-system.assessment.yml) ride dispatch checkpoint commits — exclude them from re-lands or they conflict every time.
- Measure gate-suite duration on an IDLE host before trusting a timeout bump — tony-omen's 12-file set is ~78s now vs ~483s under load; the 900s budget is for loaded idc03, not omen.
