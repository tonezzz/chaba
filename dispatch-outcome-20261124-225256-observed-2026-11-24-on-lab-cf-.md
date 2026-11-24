# Dispatch outcome — done-card-runner-defer-spam (KNB-0036 follow-through)

## What was found

The card's named fix (gate defer comms on column in {backlog,doing} before
comms_add + regression test) had already landed as PR #204 (ab861e4c28) —
claim_pass's defer-notes block. But the same off-queue exposure survived on
three more surfaces, verified live while this dispatch ran:

- `runner-agent._note_capacity_skip` wrote hostgate defer notes for ANY
  `action.status=queued` card with no column check — the two live
  review-column cards (`opencode-handoff-packet-scaffold-save`,
  `opencode-memory-freshness-check`, moved backlog→review by finish-less
  close-outs) were collecting "host overloaded"/"runner at cap" notes on
  every capacity skip.
- `runner-agent._claimable` never checked column — a done/review card with
  a stale `status=queued` passed every gate; the claim POST stayed
  reachable (board-api `do_claim` doesn't check column either).
- `kanban-dispatch` Phase-A `queued` filter and `_verdict_reason` were
  status-only — same claim/flag/defer-note exposure on the served side.

## What changed

- `scripts/board/runner-agent.py` — `_claimable()` gains a first-gate
  column check (`column in {backlog,doing}` else "off the claim queue",
  reason feeds /ready verdicts); `_note_capacity_skip()` applies the same
  column+status scope before hostgate notes. All other defer writers are
  downstream of `_claimable` or the already-gated defer block.
- `scripts/board/kanban-dispatch.py` — Phase-A `queued` list and
  `_verdict_reason()` mirror the same column scope.
- `scripts/devin/runner-tooling.manifest.json` — runner_agent sha256
  repinned (same-commit rule).
- Tests — `test_runner_defer_spam.py` gains `ClaimQueueColumnGateTest`
  (_claimable rejects done/review/lab, on-queue columns pass, capacity
  skip notes only backlog/doing); `test_dispatch_runner_resilience.py`
  gains `test_off_queue_column_card_never_claimed`; six column-less test
  fixtures gained `column: backlog` (the gate is strict — fixtures must
  look like real cards): executor_contract `_card` + kanban-dispatch
  `_run`/`_write_card` sites, runner_push_guard, runner_agent_lane,
  runner_agent_primer, runner_agent_launchd, queue_time_classify.
- Trail: `docs/ssot/jobs/kanban/2026-11-24-claim-queue-column-scope.yml`.

## Verification

- `pytest tests/board/test_runner_defer_spam.py test_runner_push_guard.py
  test_runner_agent_launchd.py` — 50 passed.
- `pytest tests/board/test_executor_contract.py` — 116 passed + 17
  subtests (6 min).
- `pytest tests/board` full suite minus the two deselections — **893
  passed**, including all lane/primer/retry/claim-order/dispatch-
  resilience batches.
- Deselected: `test_control_pane_projection.py::
  test_pane_implemented_on_board_page` — PRE-EXISTING failure:
  `stacks/web/public/apps/board2/index.html` does not exist anywhere in
  this branch's tree (verified via `git ls-tree HEAD`); unrelated to this
  change.
- `python3 -m py_compile` clean on both edited scripts; jobs YAML parses.

## Notes / not done

- board-api `do_claim` still accepts claims on any `status=queued` card —
  deliberate: it's the human/manual override door; automation now gates
  client-side. A server-side refusal would be its own card.
- The two live review+queued cards keep `action.status=queued` — root
  producer is `do_move`/finish-less close-outs not reconciling
  action.status. They are now correctly unclaimable and stop collecting
  defer notes; the stale flag itself wants a board-hygiene look if it
  recurs.
- Installed runner-agents pick this up via self-update/sync-runner-tools
  on next repo-sync; the manifest pin surfaces drift via
  runner-fleet-health.
- Pre-existing unrelated issue spotted: `scripts/ssot-prose-smell.py`
  exits 1 on `docs/ssot/jobs/board/2026-11-24-worktree-artifact-salvage.yml`
  (YAML parse error, another dispatch's file — not touched here).

## How to verify

- `python3 -m pytest tests/board/test_runner_defer_spam.py
  tests/board/test_dispatch_runner_resilience.py -q` — new gate tests.
- After merge + runner self-update: a done/review card with stale
  `action.status=queued` produces zero "X defers:" comms and zero claim
  POSTs; `/ready` verdicts show "column <c> — off the claim queue".

## lessons

- Gating defer comms is not enough — the same stale `status=queued` flag
  also reached the claim POST (`_claimable`) and the capacity-skip note
  path (`_note_capacity_skip`); audit every comms_add/claim surface, not
  just the one that spammed.
- `do_move` and finish-less close-outs leave `column` and
  `action.status` inconsistent — treat column as the claim-queue scope
  and fail closed on the mismatch.
- runner-agent.py is sha-pinned in `scripts/devin/runner-tooling.manifest.json`
  — any edit needs the repin in the same commit or
  test_runner_tooling_contract fails CI.
- Strict new gates break column-less test fixtures across many files —
  grep for real `claimable(`/`claim_pass(` callers before choosing gate
  strictness; adding `column: backlog` to fixtures is the honest fix.
- `stacks/web/public/apps/board2/index.html` is absent from this
  worktree's tree — test_control_pane_projection fails on dispatch
  worktrees regardless of changes (pre-existing, not yours).
