# Dispatch outcome — cast-loop-breaker-test-failure

## What was wrong

`tests/ada/test_cast_loop_breaker.py::test_patches_apply_clean` failed because
`integrations/ada-voice/backend/realtime_provider.cast-loop.patch` no longer
applied to ada-voice. The diverged patch was the prompt-instructions patch
(`realtime_provider.cast-loop.patch`), not `screens.delivered-zero.patch` — the
other five drop-10 patches still applied.

Root cause: ada-voice `f8d8c9a` (ada-prompt-slim, 2026-11-23) rewrote
`DEFAULT_ADA_INSTRUCTIONS` from verbose paragraphs into one-line duty rules, so
the staged patch's context lines rotted. con01's `~/CascadeProjects/ada-voice`
checkout is also 180 commits behind `origin/main`, which made the guard test a
stale HEAD.

## What changed

- `integrations/ada-voice/backend/realtime_provider.cast-loop.patch` — re-staged
  against ada-voice `origin/main` @ `2c5a9e0`. Same three rules (TARGET
  FIDELITY, FRUSTRATION BUDGET, FAILED-ACTION LOOP) rewritten as one-line
  bullets matching the post-slim instruction style.
- `tests/ada/_checkout.py` — added `materialize_ref()` and `materialize_main()`
  (prefers `origin/main`, falls back to `HEAD`); `materialize_head()` kept for
  existing callers.
- `tests/ada/test_cast_loop_breaker.py` — the drop-10 guard and scenario test
  now materialize ada-voice `origin/main` instead of the possibly-stale local
  checkout HEAD.
- `integrations/ada-voice/README.md` — drop-10 install base updated to
  `origin/main` @ `2c5a9e0`; patch description notes the post-slim refresh.
- `docs/ssot/jobs/ada/2026-11-26-cast-loop-drop10-patch-refresh.yml` — job
  record with root cause, fix, and verification.

## Verification

- `python3 -m pytest tests/ada/test_cast_loop_breaker.py -q` → **1 passed,
  1 skipped** (scenario test skips on con01: no ada-voice `.venv`).
- `python3 -m pytest tests/ada/test_cast_loop_breaker.py::test_patches_apply_clean -q`
  → **1 passed**.
- Merged-tree smoke gate (`dispatch_repos.py` `REPO_TESTS["chaba"]` set) →
  **328 passed in 155s**.
- `python3 -m pytest tests -x -q` on con01 → collection ERROR at
  `tests/ops/test_gs_tools.py` (`No module named 'numpy'`/`PIL`) — environment
  limitation, not a regression; neither system python3 nor
  `~/CascadeProjects/chaba/.venv` has numpy/PIL on con01. The actual merge gate
  uses the smoke set above, which is green.
- `tests/ada -q` on con01 still shows unrelated pre-existing failures (missing
  `httpx`/`numpy` deps and other rotted/deployed drop guards such as
  chat_send_page vs the stale local checkout, correction_command, write-fidelity
  record copy) — out of scope for this card; noted in the job record.

## How to verify

```
python3 -m pytest tests/ada/test_cast_loop_breaker.py -q
python3 -m pytest tests/board/test_merge_sweep.py tests/board/test_dispatch_close_out.py \
  tests/board/test_claim_order.py tests/board/test_queue_time_classify.py \
  tests/board/test_runner_agent_lane.py tests/board/test_runner_agent_reconcile.py \
  tests/board/test_worktree_gc.py tests/board/test_runner_push_guard.py \
  tests/board/test_board_api_mutations.py tests/board/test_board_api_liveness.py \
  tests/board/test_kanban_act.py tests/board/test_wiki_extension.py \
  tests/board/test_board_api_action_persistence.py tests/board/test_runner_tooling_contract.py \
  tests/test_ssot_validate_refs.py -x -q
```

Against ada-voice `origin/main`, all six drop-10 patches now report `applies`.

lessons:
- ada-voice prompt drops rot when upstream rewrites DEFAULT_ADA_INSTRUCTIONS
  style (verbose -> one-line rules); re-stage the patch against origin/main and
  match the new style instead of preserving old line breaks.
- tests/ada patch guards should materialize origin/main, not the local checkout
  HEAD — con01's ada-voice checkout was 180 commits behind and that alone
  rotted guards for drops that apply cleanly upstream.
- `pytest tests -x -q` is not runnable on con01 (no numpy/PIL); the real merge
  gate is the fixed REPO_TESTS chaba smoke set (328 tests, ~155s).
