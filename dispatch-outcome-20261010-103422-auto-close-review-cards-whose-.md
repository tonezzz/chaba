# Dispatch outcome — kanban-review-auto-close

**Card:** `kanban-review-auto-close` — "Auto-close review cards whose
evidence checks pass — Tony wants verified review to close itself"
(branch `dispatch/20261010-103422-auto-close-review-cards-whose-`,
commit `cabab0c9`, not pushed)

## What was wrong

merge-sweep stamped `action.verified: true` on merged dispatch cards but
never drained them: `action.status` stayed `running` and `column` stayed
`doing`/`review`, so verified cards accumulated in Tony's queue (the
2026-10-09 night hit 3 cards — fix-scenario-schedule-collision,
ci-test-gate, runner-bootstrap-check). Worse, a `status: running` +
verified card re-entered `verify_gate` each pass, and stale evidence
(head == base tip after the merge) could flip it to `verified: false` +
requeue — the "re-dispatched after verified merge" bug from the card
comms. kanban-act couldn't help: it only drains `column: review` cards
with `autonomy: t2` + `auto_done_when`.

## What changed (`scripts/board/merge-sweep.py`)

- `close_hold_reason(card)` — mirrors kanban-act's `gate_hold_reason`
  minus the column gate: `review_kind` absent/`verify` may close;
  `decide`/`triage` are human-gated; open `requests[]` and unanswered
  `ask` block the close.
- `drain_verified(card, dry)` — the close decision for an already-
  verified card (no git work; verified implies merged): `status->done`,
  `claim.session` cleared, `column->done` + an `auto_close` record
  (`by: merge-sweep`, same field shape kanban-act writes), or move
  to/stay in review when held. Idempotent — held cards get one
  `close_held`-stamped comms note, then silence; closed cards early-skip.
- Wired into three points: the `done`+verified early-skip (covers
  close_out-stamped cards and pre-drain stragglers), `stamp_gate_result`'s
  verify branch (a fresh verify applies status+column+auto_close in the
  same locked_edit), and a new check right after `merge_state` **before**
  `verify_gate` — a stamped card is never re-gated. Verified + non-
  ancestor head (commits the stamp never covered) gets one
  `verified_unmerged` flag for a human — no merge, no requeue.

Docs: `card_schema.review_kind` + `column_sla.review` in
`docs/ssot/kanban/ssot.kanban.yml` now record the auto-close contract;
runbook trail at `docs/ssot/jobs/kanban/2026-10-10-review-auto-close.yml`.

## Result

Verified `review_kind: verify` (or absent) dispatch cards close
themselves on the next sweep pass (~15 min). `decide`/`triage` cards and
anything with an open request stay human-gated in review with a one-time
explanation note.

## Verify

- `python3 -m unittest discover -s tests/board` — 96 tests, 0 failures
  (25 in test_merge_sweep incl. 6 new drain tests: fresh-merge close,
  stale-running drain, decide hold, open-request hold, triage hold,
  verified+unmerged anomaly, idempotence).
- `CHABA_REPO=$PWD BOARD_API=http://127.0.0.1:9 merge-sweep.py --dry-run`
  on this worktree's cards: `dispatch-priority-order` and
  `ada-deploy-gate-tests` report `verified — auto-close (column ->
  done)`; fresh ancestor verifies stamp + auto-close.
- Live: next `merge-sweep.timer` pass on tony-dell should move the
  verified review stragglers to done — watch for `auto-closed` comms.
