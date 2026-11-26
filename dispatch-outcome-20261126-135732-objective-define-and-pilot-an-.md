# Dispatch outcome — ansible-prep-plan-apply-verify (attempt 2)

## What I found

Attempt 1 had already delivered all OPS-1424 scope and the merge hold was
infrastructure, not code: the mn01 runner lacked `pytest`, so the chaba
merge test gate fail-closed ("pytest unavailable — no test evidence").
All attempt-1 work (SSOT prep→plan→apply→verify policy, shared benchmark
report contract, ADA-OCB preflight/plan/verify wrappers, live pilot + 4
bug fixes) was confirmed already on `origin/master` — swept into the
board-api mega-commit `62c638d3fb6`.

Reproducing the gate on this runner (con01) exposed a **real, pre-existing
master breakage**: `tests/board/test_runner_tooling_contract.py::
test_pin_hashes_match_sources` fails because `scripts/board/dispatch_repos.py`
changed in the 2026-11-26 sweep commits without a matching sha256 bump in
`scripts/devin/runner-tooling.manifest.json`. Every chaba dispatch merge
would have been held until fixed.

## What changed (this worktree, branch dispatch/20261126-135732-…)

- `28924b33705` — bumped `dispatch_repos` sha256 pin
  `d0b3bacf…` → `99038146…` (matches source on master).
- `f5981e22d21` — job trail:
  `docs/ssot/jobs/infrastructure/2026-11-26-dispatch-test-gate-pin-drift.yml`.

## Verification

Ran the exact chaba merge-gate smoke set
(`REPO_TESTS["chaba"]` in `scripts/board/dispatch_repos.py`) under
`~/CascadeProjects/chaba/.venv/bin/python` on con01:

```
300 passed in 118.09s
```

Previously it failed at `test_pin_hashes_match_sources`; now green.

## How to verify

- `git log --oneline -3` on the dispatch branch shows the two commits.
- Re-run the pytest command in the job note, or simply observe the next
  chaba dispatch merge gate pass `test_runner_tooling_contract.py`.
- Card comms on `ansible-prep-plan-apply-verify` carry the status trail.

## Notes / follow-ups

- OPS-1424 deliverables are live on master; card can move to review/done
  once this branch merges (the pin fix is what unblocks the gate).
- mn01 still has no pytest — chaba dispatches routed there will keep
  failing the test gate; worth a runner-capability note or pytest install.
- The idc02 OCB-pane SSH outage from attempt 1 was answered "proceed";
  no further action taken here.

lessons:
- board-api/board sweep commits can land dispatch worktree changes en masse — check `git log -- <file>` before assuming card work is unmerged.
- runner-tooling.manifest.json pins are merge-gate dependencies: any change to the 6 pinned sources MUST bump sha256 in the same commit or every chaba dispatch merge holds.
- chaba merge-gate smoke set (~300 tests, ~2min) runs under `~/CascadeProjects/chaba/.venv/bin/python` on con01; system python3 lacks numpy/PIL so the full suite is not a usable local check there.
- mn01 lacks pytest entirely — chaba dispatch merges originating there fail-closed at the test gate (OPS-1191).
