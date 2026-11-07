# dispatch-outcome — reproduce-tests-ada-test-tg-fo (dispatch-test-baseline-awareness)

## What was asked

Reproduce `tests/ada/test_tg_forward_provenance.py::TestHandleTurns::
test_forwarded_document_described` failing identically on origin/master
and the marker branch (`UnboundLocalError(turn_ok)`); implement a
baseline-aware merge gate that runs the same focused failure on base and
branch, classifies pre-existing failures separately, and never
suppresses new failures; validate with the OpenCode README marker probe
then a source-changing regression probe.

## Reproduction — confirmed

In a sandbox clone of origin/master (`9e70ccc36`, runner tony-macbook,
fresh `.venv` with pytest+httpx+websockets+requests+pyyaml):

- base worktree → `FAILED ...::test_forwarded_document_described` —
  `UnboundLocalError: cannot access local variable 'turn_ok'` at
  `tg_relay.py:1216` (the forwarded-document branch reaches
  `if turn_ok:` without ever binding it).
- README-marker merged worktree → byte-identical failure.

A full-suite run shows master's red set is larger: the same
`turn_ok` bug also reds `test_forwarded_sticker_described`, plus
`test_patch_state_vs_checkout` (write-fidelity patch drifted vs the
local ada-voice checkout) and — under master's own first-pass equality
gate — `test_gate_red_suite_holds_merge` /
`test_gate_timeout_holds_merge` (fake non-pytest gate commands were
baseline-compared and "passed" as identical-on-base; the new code fixes
both by only baseline-comparing python-led pytest commands).

## What changed — `scripts/board/dispatch_repos.py`

The first-pass gate (010af8dc5) compared the `-x` first failure against
a full baseline suite run with set equality. Three gaps found and fixed:

1. **-x blind spot (suppression hole).** `pytest -x` reports only the
   first failure; a NEW failure sorting after a pre-existing one was
   never compared and would merge suppressed. Now, on a red branch run,
   `_gate_failures()` re-enumerates the suite without
   `-x`/`--exitfirst` (`-rf` appended so `FAILED nodeid` lines always
   print).
2. **Focused baseline compare.** `_baseline_failures()` runs the
   branch's failing nodeids on a detached baseline worktree — ONE PER
   pytest call (a single missing pathspec, e.g. a branch-only test
   file, makes pytest exit 4 and run nothing, which would misclassify
   every pre-existing failure as new). Nodeids not failing on base —
   including ones pytest can't collect — count as new.
3. **Classification.** `new = branch_failed - base_failed`: empty →
   `ok=True, skipped="pre-existing baseline test failure"` with the
   shared set in `baseline_failed`; non-empty → `ok=False`,
   `failed=[new names]` (so `test_failures`/last_failure name the real
   regression), `baseline_failed` lists the pre-existing remainder.
   Doubt never suppresses: timeout / missing pytest / unparseable /
   non-pytest gate commands leave the hold standing.

`close_out_notes` updated: merges note "failure(s) identical to base
(pre-existing) — not blocking"; holds append
`(+N pre-existing baseline failure(s))`.

Tests: `tests/board/test_dispatch_close_out.py` +4 cases (identical
failure merges, new failure holds and is named, late-sorting new
failure not suppressed, branch-only nodeid is new).

## Validation — live sandbox probes

Driver: `baseline_aware_test_gate(<merged-wt>, "chaba", "probe-base")`
on merged worktrees of a local clone at origin/master.

- **README marker probe** (`probe/marker` = origin/master + README
  comment, mirrors the OpenCode incident): `ok: true`,
  `skipped: "pre-existing baseline test failure"`, all 5 enumerated
  failures in `baseline_failed` — the merge is no longer held.
- **Source-changing regression probe** (`probe/regression` = 1-line
  break in `scripts/bench-edu-rejudge.py` so
  `test_parse_scores_requires_all_five_valid_axes` fails — sorts AFTER
  the pre-existing failures, invisible to `-x`): `ok: false`,
  `failed: [tests/test_bench_edu_rejudge.py::RejudgeHelpers::
  test_parse_scores_requires_all_five_valid_axes]`,
  `error: "1 new failure(s) vs base (5 pre-existing)"` — the new
  failure is caught and named; pre-existing failures are not blamed on
  the branch.

## Test results

- `tests/board/test_dispatch_close_out.py`: 34/34 pass (incl. 4 new).
- `tests/board`: 195/195 pass.
- Live probes above on the real chaba suite + real origin/master base.

## Notes / follow-ups

- The reproduction needs a pytest-capable env with `httpx`,
  `websockets`, `requests`, `pyyaml` — this runner has no pytest
  system-wide, so the real gate here currently fail-opens ("pytest
  unavailable"). The enum run adds one full suite pass (~170s on chaba)
  only when the `-x` gate is already red; green merges are unchanged.
- `turn_ok` UnboundLocalError is a real bug in the tg-forward-provenance
  drop (`integrations/ada-voice/backend/tg_relay.forward-provenance.
  patch` vs live tg_relay) — it reds 2 tests on master and deserves its
  own fix card; the gate classifying it pre-existing is correct
  behavior, not a fix.

## How to verify

1. `pytest tests/board/test_dispatch_close_out.py -x -q` (needs real
   pytest) — the 4 `test_gate_baseline_*` cases.
2. Code review: `baseline_aware_test_gate`, `_gate_failures`,
   `_baseline_failures`, `_gate_failfast_strip` in
   `scripts/board/dispatch_repos.py`; note formatting in
   `close_out_notes`.
3. Trail: `docs/ssot/jobs/kanban/2026-10-26-baseline-aware-test-gate.yml`.
