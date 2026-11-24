# Dispatch outcome — runner-dispatch-no-timeout (OPS-0999)

## What changed

Bound every unattended headless dispatch lane by wall-clock time and
added a denial-count circuit breaker for opencode runs.

- `scripts/devnest/opencode_stream_guard.py` (new): wraps the opencode
  child, tees its JSONL event stream to the taskdir events file, and
  kills the child after N consecutive tool permission denials
  (default 10; `action.denial_streak_max` or
  `OPENCODE_DENIAL_STREAK_MAX` override; 0 disables). On trip it writes
  `denial-breaker.json` in the taskdir and exits 3.
- `scripts/board/runner-agent.py`:
  - `start_kk_mac_lane`: `rt_launch(timeout_s=action.timeout_s or 900)`
    — the kk_mac unit was previously unbounded.
  - `start_nlm_lane` (both duplicate defs, second shadows first):
    `timeout_s=action.timeout_s or 1800`.
  - `_start_opencode_lane`: RuntimeMaxSec was already armed via fixture
    `task.yaml timeout_s` → `action.timeout_s` → 420s default
    (commit 77d8d9b38f); the unit shell now pipes opencode through the
    stream guard (falls back to plain `tee` if absent).
  - devin-dispatch path: `DISPATCH_UNIT_PROPS` appends
    `--property=RuntimeMaxSec=<n>` only when the card declares
    `action.timeout_s` — opt-in, since devin sessions legitimately run
    long.
- Tests: `tests/devnest/test_opencode_stream_guard.py` (streak logic +
  CLI kill/marker/passthrough), `KkMacLaneTimeoutTest` in
  `test_executor_contract.py` (systemd-run argv carries
  RuntimeMaxSec=900 default / =123 override),
  `test_action_timeout_s_arms_runtime_max_sec` in
  `test_runner_agent_lane.py` (DISPATCH_UNIT_PROPS).
- Job doc: `docs/ssot/jobs/devnest/2026-11-24-runner-dispatch-bounded-units.yml`.

## Result

`pytest tests/devnest/test_opencode_stream_guard.py
tests/board/test_runner_agent_lane.py
tests/board/test_executor_contract.py -x -q` → 145 passed, 17 subtests.
Commits on `dispatch/20261124-172726-found-during-devnest-fl-pilot-`:
`1754d8f64b` (guard + tests), `e6083baf77` (job doc); runner-agent and
test edits landed in checkpoint commit `7dc2187b7d`.

## How to verify

- Guard: `python3 scripts/devnest/opencode_stream_guard.py --events
  /tmp/ev.jsonl --max-streak 5 --marker /tmp/denial-breaker.json --
  python3 -c '...'` — denial spam exits 3 and writes the marker.
- Lane bounds: `systemctl --user show devin-task-<tid> -p
  RuntimeMaxUSec` on a live unit, or inspect the `systemd-run` argv in
  the tests above.

lessons:
- runner-agent.py contains duplicate `start_nlm_lane`/`finish_nlm_lane`
  definitions — the second silently shadows the first; patch both or
  the dead copy drifts.
- `rt_launch(timeout_s=N)` is the single choke point that maps to
  `--property=RuntimeMaxSec` on systemd and the pgrp watchdog on
  launchd — arm timeouts there, never hand-roll systemd-run args.
- The dispatch/devin lane deliberately has no default wall-clock bound;
  only card-declared `action.timeout_s` opts in — don't "fix" it by
  adding a blanket default.
- Dispatch session compaction commits ("Compaction summary for session
  ...") sweep the working tree into HEAD mid-session — `git status`
  showing clean does NOT mean your edits are uncommitted; check
  `git show HEAD:<file>` before assuming work was lost.
