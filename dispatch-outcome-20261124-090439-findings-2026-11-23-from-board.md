# dispatch outcome — devin-lane-cheap-ops-reroute (2026-11-24, attempt 2)

## Context

Tony answered "proceed" (09:02) to request
`dev-0045-slice-2-decision-measurement-in-4cbe90` = keep the deployed
cheapest-capable-first lane order (free_lane before devin) and watch
the misroute rate. Prior slices already merged: classifier reroute
(host kw removed, free_lane-first, timer-alert guard → free_lane) +
claim-time lane_source provenance. This session delivered the
re-measure + the durable watch; no classifier keyword changes
(option-b narrowing was not chosen).

## What changed

- `scripts/board/kanban-stats.py` — new "Lane routing — open cards"
  section: lane × lane_source matrix over non-done cards
  (`pin` = author-set, wins forever; kw/claim/fallback/jevos/
  timer-alert = classifier stamps that re-evaluate on re-queue) +
  unstamped `type:dispatch` count. Runs every 15 min via
  kanban-sync.timer on the served checkout → the misroute watch is
  continuous, not a manual audit.
- `tests/board/test_kanban_stats_lane.py` — new, 5 tests.
- `scripts/devin/runner-tooling.manifest.json` — briefly bumped the
  `dispatch_repos` pin after finding the contract test RED on master
  (the 081047 dispatch changed the source without bumping). On
  rebase the bump was dropped as obsolete: upstream dispatch
  20261124-080849 landed a newer dispatch_repos.py AND correctly
  bumped all pins — origin/master is self-consistent.
- Trail doc: `docs/ssot/jobs/board/2026-11-24-devin-lane-reroute-watch.yml`.

## Re-measure (339 open cards, board-api fetch 2026-11-24 ~09:10)

classify_lane(with_detail=True): free_lane 159, devin 117,
paid_frontier 40, codemod 21, manual 2. Sources: kw 183, fallback 96
(JEVOS unreachable from tony-omen — no-kw cards default devin, the
safe fallback; served-host jevos may resolve some differently),
timer-alert 45, explicit 15. Consistent with the prior post-flip
measure — the flip is the new steady state.

## Misroute spot-check (watch list, per proceed they stay as-is)

Confirmed false-cheap flips still live on backlog:
ai-video-quality-control-plane → free_lane kw:plan,
ops-retry-storm-detection → free_lane kw:try,
kk-mac-launchd-runner-followthrough → free_lane kw:launch,
logs-digest-program → free_lane kw:report. Blast radius bounded:
free_lane needs a staged lane_envelope or the card holds at claim
(no attempt burned) — observed live when this card itself held on
idc02/tony-dell. Residual noted: timer-alert-idc03-ada-scenario-smoke
carries a bare devin lane (no lane_source) → reads as author pin,
overrides the tag guard; likely a legacy pre-provenance claim stamp.

## Verification

- `python3 -m unittest tests.board.test_kanban_stats_lane
  tests.board.test_runner_tooling_contract
  tests.board.test_queue_time_classify tests.board.test_codemod_lane_gate
  tests.board.test_runner_agent_lane` — 81 tests OK pre-rebase;
  re-run post-rebase against upstream's newer dispatch_repos.py.
- `python3 scripts/board/kanban-stats.py --check` renders the matrix
  on live card YAMLs.
- Full `tests/board` discover: **886 tests, OK** (~16min).

## How to verify

- Card comms on `devin-lane-cheap-ops-reroute`; job doc above.
- After merge + served-checkout pull: `reports/kanban/kanban-stats.yml`
  and the system-report `kanban.md` carry the lane-routing matrix.

lessons:
- runner-tooling.manifest.json pin drift is NOT self-healing: any
  dispatch that edits a pinned tool must bump sha256 in the same
  commit — the 081047 dispatch missed it and left the contract test
  red on master for ~30min until this session caught it.
- "watch X rate" decisions need a durable surface to be real —
  kanban-stats.py (15m timer, already mirrored to system-report) was
  the right host for the lane-routing matrix vs a standalone script.
- free_lane misroutes are mostly cosmetic until envelope-staged:
  unstaged free_lane cards HOLD at claim (no attempt burned), so
  false-cheap keyword flips only cost anything on hosts with drifted
  runner-agents — fleet tool sync is part of the blast-radius story.
- classify_lane's jevos fallback means kw-less cards read
  fallback→devin when JEVOS is unreachable; measure from a host
  where 127.0.0.1:8017 answers or annotate the caveat.
