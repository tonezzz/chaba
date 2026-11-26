# Dispatch outcome — lane-retention.py summary crash (ADA-1370)

Card: `lane-retention-py-crashes-at-summary-swe-b888ce`

## What I found

The card's stated mechanism does not exist in the repo: `prune.sweep()`
has returned a bare `str` in **every** committed version of
`scripts/ada/prune-old-docs.py` (checked full `git log --all` history),
and `sweep_ops()` has always appended those strings — `sweeps` is
`list[str]` on every branch. No code path in git can put a tuple in
front of `re.search(r"deleted (\d+)/", line)`.

That means the 2026-11-25 09:57 exit-code on all four `ada-retention-*`
services came from a **deployed file that diverges from origin/master**
— most likely an uncommitted local edit or stale copy in idc03's
`~/CascadeProjects/chaba` exec checkout. Worth verifying on idc03 with
`git -C ~/CascadeProjects/chaba status` / `git diff scripts/ada/`.

## What I changed (robust to both shapes, per the card's fix options)

- `scripts/ada/lane-retention.py` — `sweep_ops()` now normalizes each
  `prune.sweep()` result before appending: `(line, ok)` tuple/list →
  first element; non-`str` results dropped. Its `-> list[str]` contract
  now holds no matter which `prune-old-docs.py` variant is deployed, so
  the summary-phase regex can never see a tuple again.
- `tests/ada/test_lane_retention.py` — added `TestSweepOps` (str
  passthrough, tuple unwrap, non-str drop) and `TestMainOpsOnly`, an
  end-to-end `--ops-only` `main()` run with a tuple-returning
  `prune.sweep` stub.
- `docs/ssot/jobs/ada/2026-11-25-lane-retention-sweep-tuple-fix.yml` —
  job note recording the root-cause finding and the idc03 verification
  step.

## Verification

- `python3 -m pytest tests/ada/test_lane_retention.py` — 28 passed.
- Red/green check: stashing the `lane-retention.py` fix makes
  `TestMainOpsOnly` fail with the **exact** reported error —
  `TypeError: expected string or bytes-like object, got 'tuple'` —
  after the ops-sweep phase logs the tuples; restoring the fix → green.
- `python3 -m py_compile scripts/ada/lane-retention.py` — OK.

## Notes for the reviewer

- The fix is defensive: it cannot regress the current (str-returning)
  path, and it immunizes the crash site against the tuple shape the
  deployed copy apparently produces.
- If idc03's checkout has uncommitted edits to `scripts/ada/`,
  `git-safe-pull`'s autostash may resurrect them — the divergence check
  above is the real follow-up; this patch makes the job survive either
  way.
- Card comms + this file are the deliverables; no push/deploy per
  dispatch rules.

lessons:
- Card-reported root causes can describe the deployed state, not the repo — diff git history before trusting the mechanism; a defensive fix at the contract boundary covers both.
- `unittest.mock.patch.object(..., side_effect=lambda *a: next(it))` is a clean way to feed per-call stub sequences in these offline tests.
- Reproducing the crash red-first (stash fix → run new test → exact TypeError) is cheap proof the regression test bites.
