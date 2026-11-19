# Dispatch outcome — dispatch-failed-cards-park-in-doing (retry 20261119-083115, tony-omen)

## What was found
The design and implementation already existed. The 2026-11-18 run (`dispatch/20261118-221757-decide-implement-the-stalled-c`, tony-dell) built the stalled-claim lifecycle and exited ok. Its branch was pushed, but **the auto-merge to master was rejected** (non-fast-forward, "fetch first") and the worktree was then GC'd. So the fix never reached master or any host. The live board still shows the original bug.

Full design: `docs/ssot/jobs/kanban/2026-11-18-stalled-claim-lifecycle.yml`, plus `dispatch-outcome-20261118-221757-…md` (carried in by the merge).
- (a) Every claim-ending path (finish/fail, launch fail, dead-runner requeue, merge/verified-gate fail, retry-cap park, queue/retry verbs) leaves `doing`. Under `KANBAN_MAX_ATTEMPTS=2` the card is auto-requeued to backlog; at the cap it is parked `failed` in backlog, and `/action do=retry` re-arms it.
- (b) A reaper lane in merge-sweep runs on the 15-min janitor tick:
  - failed/held/queued/stale-starting cards go doing→backlog, and `done` cards go to review.
  - A live-looking claim with no unit and no heartbeat for more than 6h is flagged, never auto-moved.
  - An orphan doing card with no claim is flagged first, then moved on a later pass if nobody has touched it.
- (c) Claims stamp `claim.since` and bump attempts. `/queue` claimed[] now counts `starting`, so doing-count == claimed+active.

## What this run did
- Merged `origin/dispatch/20261118-221757-…` into this branch on top of current master. The merge was clean, with no conflicts.
- `py_compile` passes for board-api, kanban-dispatch and merge-sweep. `tests/board/test_stalled_claim_lifecycle.py` + `test_dispatch_close_out.py`: **66 passed**. Full `tests/board/`: **664 passed** (6m55s).
- Live evidence (2026-11-19 08:34): the board has 25 cards in doing (23 dispatch/failed, 1 done, 1 running), while `/queue` shows claimed=2 and 4 active units fleet-wide. A dry-run of `reap_stalled_claims` on that snapshot gives 24 moves (23→backlog, 1→review). That leaves only the live claim, so after deploy, doing-count == `/queue` claimed+active.
- Appended a `landing_2026_11_19` section to the job doc.

## Not done (gates)
No push or deploy, per the rails. To finish:
1. Merge `dispatch/20261119-083115-decide-implement-the-stalled-c` to master.
2. Redeploy board-api (restart on idc03), kanban-dispatch, merge-sweep and runner-agent on the hosts.
3. After one janitor tick, check that doing-count (`grep -l '^column: doing' docs/ssot/kanban/cards/*.yml | wc -l`) equals `/queue` claimed + active. Then queue a throwaway card, let it defer or fail, and confirm it lands in backlog and gets re-claimed.

## Verify locally
`python3 -m pytest -q tests/board/test_stalled_claim_lifecycle.py tests/board/test_dispatch_close_out.py`
