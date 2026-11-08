# dispatch-model-pick-executor-mismatch — outcome

## What was wrong

`LANE_MODELS` values are all `litellm/*` ids — valid only for the
opencode executor (`opencode --model` takes provider/model). Three
places fed them to `devin --model` regardless of the resolved executor:

1. `runner-agent.claim_pass` persisted lane→model into the claim body
   for any undeclared-executor card, even when the claiming host had no
   opencode route (`OPENCODE_LANES=0` or no resolvable profile) — a
   devin-bound claim got `action.model=litellm/...` written to the board.
2. `runner-agent.start_task`'s env fallback re-read `action.lane` and
   mapped `LANE_MODELS` even on the `executor=devin` path.
3. `kanban-dispatch.start_pending` did the same via
   `elif lane in LANE_MODELS` and persisted litellm picks into
   `action.model`. A stale litellm `action.model` (earlier claim, or a
   reclassified lane keeping `not a.get("model")`) then poisoned later
   devin claims — exactly the observed
   `provider=litellm model=litellm/gemini-3.5-flash-lite` +
   `executor=devin` meta on `devin-task-20261108-071214`.

## Fix (commit 3c43db4ac on dispatch/20261108-081128-...)

Contract: provider and executor namespaces must match — bare devin ids
for the devin executor, `provider/model` ids for opencode; no valid id
→ empty model (executor default).

- `scripts/board/dispatch_repos.py`: new `model_valid_for_executor()` +
  `lane_model()` helpers.
- `scripts/board/runner-agent.py`: local mirrors (file deploys
  standalone); claim-time persist gated on the route the claim resolves
  to; `DISPATCH_MODEL` namespace-checked — a dropped card-declared model
  posts a chaba comms note, lane-table picks stay quiet;
  `start_opencode_lane` model precedence now picks the first candidate
  valid for opencode.
- `scripts/board/kanban-dispatch.py`: same check in `start_pending`;
  lane→model persist uses `dr.lane_model(lane, "devin")`.
- `tests/board/test_runner_agent_lane.py`: new coverage for the drop +
  comms note, devin-id passthrough, lane pick kept off `DISPATCH_MODEL`,
  and claim persist gated by `OPENCODE_LANES`; updated claim-pass
  expectations.
- Trail: `docs/ssot/jobs/board/2026-11-08-dispatch-model-executor-namespace.yml`.

## Verify

- `python3 -m unittest tests.board.test_runner_agent_lane` — 18 tests OK.
- `python3 -m unittest tests.board.test_executor_contract
  tests.board.test_kanban_dispatch_rails tests.board.test_claim_order
  tests.board.test_dispatch_close_out tests.board.test_queue_starvation
  tests.board.test_runner_agent_reconcile tests.board.test_runner_agent_gpu
  tests.board.test_worktree_gc` — 176 tests OK (6 skipped).
- `python3 -m py_compile` on all three edited scripts — clean.
- Board comment posted to the card.

Note: pre-existing `action.model=litellm/*` values on cards are not
deleted — the launch guard drops them per-claim (with a comms note when
card-declared) and a later opencode-capable re-claim can still use them.
`paid_frontier` has no opencode profile mapping, so it always resolves
devin today and its litellm pick is never used.
