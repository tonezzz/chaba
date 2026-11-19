# Dispatch outcome — merge-sweep-test-gate-fail-open (OPS-1191), attempt 2

## Summary

Re-landed the fail-closed merge test gate from the prior attempt's branch
`dispatch/20261119-131744-observed-on-hands-off-waiting-` (which had pushed
correct work but was held on a suite timeout, then a zombie-claim retry
produced nothing) onto current master via a clean merge commit — no
conflicts across 234 newer master commits. The re-landed design (decided
under Tony's approved direction): `run_test_gate` fails CLOSED on an
unrunnable pytest gate (`gate_unrunnable` holds the merge), a bounded
flock-serialized bootstrap provisions the canonical checkout's `.venv`
with `REPO_TESTS[repo]['bootstrap']` deps (`KANBAN_GATE_BOOTSTRAP=0` opts
out), `action.test_exempt` is the docs-only allowlist, merge-sweep runs
the same baseline-aware gate in `merge_strict` before push with a
head-keyed `action.sweep.gate_blocked` stamp, and runners auto-advertise
a `pytest` label so unrunnable requeues route only to gate-capable hosts.
New in this attempt: measured the full chaba gate set at 237 tests /
482.8s on tony-omen under load — the old 240s timeout could never pass,
which is what held the prior merge; raised `REPO_TESTS['chaba'].timeout`
to 900s so a green suite is not wedged (noted in the runbook). Tests:
`test_dispatch_close_out.py` + `test_merge_sweep.py` 95/95 pass; full
gate set 237/237 pass.

## What changed

- Merged `origin/dispatch/20261119-131744-observed-on-hands-off-waiting-`
  (commits `388a39909d` + `6bfa433ee8`) into this branch — brings:
  - `scripts/board/dispatch_repos.py` — fail-closed `unrunnable` gate
    result, `_bootstrap_gate_python` repo-scoped venv provisioning,
    `pytest_capable()` probe, `action.test_exempt` skip, card plumbed
    through `baseline_aware_test_gate`/`_merge_and_gate`/`close_out`/
    `close_out_notes`.
  - `scripts/board/merge-sweep.py` — `merge_strict` runs the gate
    pre-push; held heads stamp `sweep.gate_blocked` (head-keyed, no
    re-gate churn); merged comms carry gate evidence.
  - `scripts/board/kanban-dispatch.py` — `MY_LABELS` auto-adds `pytest`;
    unrunnable requeues gain `labels:[pytest]`.
  - `scripts/board/runner-agent.py` — same `pytest` auto-advertise;
    `gate_unrunnable` treated as non-merge result.
  - `docs/ssot/kanban/ssot.kanban.yml` — schema/execution prose updated.
  - `docs/ssot/jobs/kanban/2026-11-19-merge-test-gate-fail-closed.yml` —
    runbook (decision, behavior, ops/redeploy notes, edge cases).
  - Tests: fail-open tests replaced with fail-closed coverage in both
    board test files.
- `scripts/board/dispatch_repos.py` — `REPO_TESTS['chaba'].timeout`
  240 → 900 (suite needs ~480s at load; the old budget held every merge
  on "suite timeout").
- `docs/ssot/jobs/kanban/2026-11-19-merge-test-gate-fail-closed.yml` —
  edge-case note on the timeout bump.

## Result

Pass locally — 95/95 focused board tests, 237/237 full gate set.
Remaining follow-through is operational, not code: once this branch
merges, the served checkout on idc03 picks up the gate via kanban-commit
pull, and `runner-agent.py` should be redeployed to fleet hosts so the
`pytest` auto-advertise is live (fleet drift notes already on the card).

## How to verify

- `python3 -m pytest tests/board/test_dispatch_close_out.py tests/board/test_merge_sweep.py -x -q`
- `python3 -c "import sys; sys.path.insert(0,'scripts/board'); import dispatch_repos as dr; print(dr.test_gate_config('chaba'))"` → `timeout: 900`, `bootstrap: [pytest, pyyaml]`
- On a pytest-less host a chaba dispatch merge now holds with
  "test gate could not run — merge held (fail-closed)" and the card
  requeues with `labels:[pytest]`, or the canonical checkout gains
  `.venv/bin/pytest` via the bounded bootstrap.

lessons:
- Re-landing a pushed-but-unmerged dispatch branch is a plain merge onto the new dispatch branch — check `git branch -a` for prior attempt branches before re-implementing from scratch.
- A merge gate whose suite can't fit its timeout wedges every merge fail-closed — measure the real suite duration on the slowest expected host before setting the budget (chaba's 12-file set: ~480s on tony-omen under load vs 240s configured).
- The merge-sweep's own temp-worktree gate run means a pytest-less RUNNER is safe, but the SWEEP host still needs a runnable gate (or bootstrap) — both paths were covered, verify both.
- Zombie-claim retries can produce "no delivered work" attempts; check card comms for the earlier pushed branch rather than assuming the work is lost.
