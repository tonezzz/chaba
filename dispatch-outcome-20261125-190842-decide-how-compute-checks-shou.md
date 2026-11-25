# Dispatch outcome — render-board-checks-task-id-dead-path

Card: `render-board-checks-task-id-dead-path` (KNB-1366)
Session: devin-dispatch `20261125-190842-decide-how-compute-checks-shou` on tony-dell

## Decision

Chose a card-local variant of option (b) + (a) as last resort — NOT (c).

- **(c) rejected**: the git chips carry real merge-truth signal (the
  verify-by-surface evidence the sweep duty relies on) and the git path
  was already optimized in render-board-real-cost-git-subprocesses;
  only the task-id leg was dead.
- **(b) partially rejected**: `claim.session` is empty on 0/432 dispatch
  cards, and merge-sweep's `task_id_for` state.json leg needs per-card
  ssh to runner hosts — exactly the subprocess cost the render path
  exists to avoid.
- **Adopted**: `_task_id_for(c)` in `scripts/render-board.py` mirrors
  merge-sweep's card-local chain — `action.task_id` → `claim.session` →
  comms `devin-task-<id>` (newest first) → `action.result` — all from
  already-parsed card fields, zero subprocesses. Heuristic legs are
  gated on `action.type == "dispatch"` so non-dispatch cards that
  merely mention a task id can't borrow another run's chips.

## What changed

- `scripts/render-board.py`: added `_TASK_ID_RE` (mirrors
  merge-sweep.TASK_ID_RE — covers `<ts>-<slug>` devin tids AND
  `<card-id>-<epoch>` opencode/kk_mac/nlm tids), `_task_id_for()`,
  `_runs_for_slug()` (ambiguity-guarded prefix fallback for
  result[:300]-truncated slugs); `compute_checks` now resolves tid via
  `_task_id_for` and runs via `_runs_for_slug`. render-board2 inherits
  the fix through `_rb.compute_checks`.
- `tests/board/test_render_board_outputs.py`: +7 tests — chain order,
  newest-first retry, comms truncation extension, non-dispatch gate,
  opencode tid form, prefix ambiguity, compute_checks regression.
- `docs/ssot/jobs/board/2026-11-25-render-board-checks-task-id-recovery.yml`:
  decision + evidence trail.

## Truncation wrinkle found live

Comms notes (finish/merge-sweep lines) embed **truncated** tids —
`ada-session-summary-inflow-stalled`'s newest comms mention was
`devin-task-20261125-150157-found-while-shi` while the `started` line
held the full `...-shipping-memory-ex`. `_task_id_for` collects all
comms tids newest-first and extends the newest with the longest
same-run prefix-variant (different runs differ at the timestamp and
never prefix-match).

## Verification

- Unit: `pytest tests/board/test_render_board_outputs.py` — 10 passed;
  `test_merge_sweep.py` + render-guard — 57 passed.
- Live corpus (800 cards, 82 run slugs): **before** 652 cards with
  checks / **0 code chips**; **after** 655 cards with checks /
  **76 code chips** (51 merged, 25 not-merged) + 6 multi-run chips.
  tid recovery: 392/432 dispatch cards (comms 391, result +1;
  action.task_id & claim.session are 0 everywhere). The 40 without a
  tid are queued/idle/manual/non-devin-task lanes — correctly chip-less.
- Required check: card `ada-session-summary-inflow-stalled` — real
  merged run `dispatch/20261125-150157-found-while-shipping-memory-ex`
  (ancestor of origin/master) — recovers the FULL tid and renders
  `code ok=True` ("on origin/master (ancestry or patch-equiv)"),
  plus outcome/deploy/verify chips.
- tests/board suite: 228+ passed; only failures are
  test_control_pane_projection tests needing gitignored generated
  files (board2/index.html, cards.json) absent in fresh worktrees —
  pre-existing environment issue, unrelated to this diff.

## Follow-up noted (not done)

runner-agent's claim_pass has `tid` in scope after start_task — stamping
`action.task_id` durably at claim would make the comms scan unnecessary
for future renders. Card-worthy if the heuristic ever proves lossy.

lessons:
- board-api caps action.result at 300 chars and comms notes cap text —
  devin-task-<id> recovered from card text can be a strict prefix of the
  real id; extend via same-run prefix-variants, never exact-match only.
- runner-agent claims stamp neither action.task_id nor claim.session —
  'started devin-task-<id> on <host>' comms (posted for every lane at
  claim) is the universal card-local session pointer.
- dispatch branch slugs come from the first ~30 slugified chars of the
  composed task text, not the card id — cards with similar specs share
  run branches; chips are slug-scoped, not card-scoped.
- tests that read gitignored generated artifacts (board2/index.html,
  cards.json) fail in every fresh dispatch worktree — pre-existing,
  not a regression signal.
