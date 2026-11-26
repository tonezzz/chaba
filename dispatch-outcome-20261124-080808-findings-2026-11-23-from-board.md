# dispatch outcome — devin-lane-cheap-ops-reroute (2026-11-24)

## What I found

- The prior session's classifier slice was NOT lost — it is committed on
  `origin/fix/devin-lane-reroute` (ae45a7ac22) and cherry-picked onto the
  idc03 served checkout, but it never reached `origin/master`. This
  dispatch merged that branch into the dispatch branch (merge
  6f22b8a28b), so close-out lands it on master.
- Deeper root cause behind the audit's `explicit=16` bucket: claim-time
  lane stamps carried NO `lane_source` provenance. `board-api do_claim`
  persisted `body.lane` verbatim; runner-agent's claim body had no source
  field; kanban-dispatch's JEV_LANE path wrote `a["lane"]` without
  provenance. Bare stamps read as author pins forever — a fixed
  classifier could never unstick them. This is why timer-alert-* and
  other ops cards kept reading `explicit`.

## What changed (commit 33553f1168 on dispatch/20261124-080808-...)

- `scripts/board/board-api.py` `do_claim`: stamps `lane_source` on
  claim-set lanes — body value > existing > `"claim"` — unless the card
  already holds an author pin (lane with no lane_source).
- `scripts/board/runner-agent.py` claim_pass: sends
  `lane_source="claim"` only when the lane came from fresh claim-time
  classification; re-sent author pins carry none.
- `scripts/board/kanban-dispatch.py` `start_pending`: JEV_LANE classify
  now uses `with_detail=True` and persists the source prefix.
- `scripts/devin/runner-tooling.manifest.json`: sha256 pins bumped for
  `runner_agent` + `dispatch_repos` — the prior slice changed both
  sources without bumping (contract violation the suite caught).
- Tests: +4 `do_claim` provenance cases (test_stalled_claim_lifecycle),
  +2 runner claim-body cases (test_runner_agent_lane), and a latent
  `import unittest.mock` fix in test_stalled_claim_lifecycle.
- Trail doc: `docs/ssot/jobs/board/2026-11-24-devin-lane-claim-provenance.yml`.

## Verification

- Targeted suites: 116 tests OK (stalled_claim_lifecycle,
  runner_agent_lane, runner_tooling_contract, queue_time_classify,
  codemod_lane_gate, board_api_action_persistence).
- Full `tests/board` discover: 874 tests — 1 pre-existing env error
  (`test_ada_job_envelope` needs pytest, not installed on this host) and
  the pin-hash failure which this commit fixes.
- Re-measure (660 cards fetched 2026-11-24): of 39 `action.lane=devin`
  cards the merged classifier re-routes 3 to free_lane; 17 carry no
  lane_source (explicit-looking — legacy claim stamps + true pins).
  Over 350 open cards old-vs-new: devin 220→126, free_lane 64→161.
  ~50 flips = backlog timer-alert-* via the tag guard (intended);
  ~44 = free_lane-before-devin keyword hits, with observed false-cheaps
  on multi-step epics.

## Open decision (raised on card, awaiting Tony)

Request `dev-0045-slice-2-decision-measurement-in-4cbe90`: keep
free_lane-first as deployed (recommended — contract cheapest-first,
bounded blast radius since free_lane only saves burn on OPENCODE_LANES
hosts) vs narrow the broad free_lane keywords to title-scoped vs
restore devin-before-free_lane.

## How to verify

- `python3 -m unittest tests.board.test_stalled_claim_lifecycle
  tests.board.test_runner_agent_lane tests.board.test_runner_tooling_contract`
- Card comms + request on `devin-lane-cheap-ops-reroute`; job doc above.

lessons:
- runner-tooling.manifest.json pins EVERY scripts/board + scripts/devin
  single-file tool by sha256 — any edit to runner-agent.py or
  dispatch_repos.py MUST bump pins in the same commit or
  test_runner_tooling_contract fails (the prior DEV-0045 slice missed it).
- Claim-time lane stamps need lane_source provenance or they read as
  author pins forever; bare `action.lane` writes are the bug pattern.
- Dispatch worktree branches can hold work the card comms claim is
  "deployed" — always `git fetch` + check origin branches before
  re-implementing; here the fix lived on origin/fix/devin-lane-reroute.
- Free_lane only saves devin burn on OPENCODE_LANES=1 hosts — on other
  hosts the litellm/* model is stripped (OPS-1127) and devin default
  runs anyway, so lane flips there are cosmetic.
- tests/board/test_stalled_claim_lifecycle.py used unittest.mock without
  importing it — passed only via cross-module import order; now fixed.
