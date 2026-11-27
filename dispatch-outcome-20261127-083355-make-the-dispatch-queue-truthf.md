# dispatch outcome — kanban-queue-manual-handoff (2026-11-27)

## What I found

The core queue-truth work was **already landed and live** — commit
`33a06385718` (2026-11-20, "fix(board): keep human-owned cards out of the
dispatch queue") implemented the write-door invariant, the `/queue`
`human_waiting` split, and the answer-sweep/kanban-dispatch guards, and was
deployed + verified on idc03 the same day (card comms 11:45/12:01). Tony
re-spawned the card 2026-11-27 08:32 ("re-spawned from report page",
batch note re-affirming the write-door-first decision), so this session
was a verify-and-finish pass.

Verified already-correct:

- `/action do=queue|retry`, `/card queue:true`, `/card on_exists:queue` all
  refuse/park `type=manual`, `executor=manual`, `lane=manual`, and types
  outside `dispatch_repos.SERVED_TYPES` — never auto-flip type, always a
  comms reason + `awaiting_action`.
- `GET /queue` live on idc03 returns `counts {queued:0, human_waiting:0,
  claimed:7}` with `human_waiting[]` carrying kind/owner/next_action.
- Repo scan: zero cards at `action.status=queued` in the snapshot.
- ADA-0783 (`ada-text-model-promotion-path`) resolved itself — re-armed as
  `type=dispatch`, ran 2026-11-26, now `done`+`verified`; the promotion
  decision stayed with Tony per the card note. Non-goal respected.

## What I changed (the residue this pass closed)

- `scripts/render-board2.py` — Needs Tony band now lists `awaiting_action`
  cards not covered by an open request/ask, each with owner + reason +
  next action (`waitInfoAct` mirrors board-api `queue_wait_reason`/
  `_wait_kind`); in-flight/done cards excluded; `nyItemKey` fixes flash/
  count keys; ny pill counts the same rows. Cycle-pane claim reason says
  `queued but <reason>` for legacy queued-but-unclaimable cards; modal
  Start button suppressed for human/unserved waits.
- `scripts/render-board.py` — classic board needs-you rows show
  `waitReason()` (same human/unserved reason + owner) instead of the
  generic "answer recorded — needs triage", and the queue button is
  suppressed for human-waiting cards.
- `scripts/board/board-invariants.py` — Q1 extended from
  `type != dispatch` to the full never-claimable contract
  (`_queue_block_reason`: executor=manual, unknown executor fail-closed,
  lane=manual, type=manual, unserved type); legacy non-dispatch flag kept.
- `scripts/board/board-api.py` — `do=finish` failure auto-retry now checks
  `queue_wait_reason` first; a human-owned card parks at
  idle+awaiting_action instead of being re-armed.
- `tests/board/test_board_invariants.py` — new (6 tests).
- `tests/board/test_control_pane_projection.py` — contract assertions for
  both board surfaces.
- `docs/kb/board-api-write-door.md` + `docs/ssot/jobs/board/
  2026-11-27-kanban-queue-truth-board-surfaces.yml` — trail.

## Verification

- `pytest tests/board/test_queue_starvation.py` — 29 passed
- `pytest tests/board/test_board_invariants.py` — 6 passed
- `pytest tests/board/test_control_pane_projection.py` — 8 passed
- Focused board suite (queue-starvation + invariants + control-pane +
  answer-sweep + executor-contract): 211 passed, 17 subtests
- `board-api.py --selftest` — ok
- `node --check` on generated board2 + classic JS — ok; node harness over
  `nyItems`/`waitInfoAct` confirmed correct kind/owner and no dup rows
- Live `GET /queue` — clean; dispatch cards still claim (7 claimed)

Note: `test_pane_implemented_on_board_page` /
`test_pane_data_contract_on_board_payload` need the gitignored generated
`stacks/web/public/apps/board2/` artifacts — I ran
`render-board2.py`/`render-board.py` locally to produce them; on a fresh
checkout they fail until rendered (pre-existing condition, unrelated).

## Residual (documented in the jobs file)

kanban-dispatch `requeue_dead`/`_fail_or_requeue`/`merge_pending_one` and
merge-sweep `fail_attempt` auto-requeue paths carry no human-wait guard —
unreachable in practice (they require a prior claim/run, impossible for
manual cards through any door); a YAML-bypass mid-run type flip could
still leave one queued, which `/queue` human_waiting + Q1 then surface.

## Lessons

- `awaiting_action` is the human-waiting parking state — any new queue
  surface must read it, not just `action.status`, or parked cards go
  invisible (board2 had exactly this gap).
- board-api's queue-truth contract lives in three functions
  (`human_wait_reason`/`queue_wait_reason`/`_wait_kind`); JS renderers
  re-implement it — keep the mirror in `waitInfoAct`/`waitReason`
  semantically identical or the surfaces disagree.
- `stacks/web/public/apps/board2/` is gitignored generated output —
  control-pane contract tests fail on fresh worktrees until you run
  `render-board2.py` once.
