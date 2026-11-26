# Dispatch outcome — auto-route bounded card classes to executor=claude

Card: `auto-route-bounded-card-classes-to-execu-257c7a` (attempt 2;
attempt 1's work was never committed — implemented fresh).

## What changed

Classifier policy so bounded card classes self-route to
`executor=claude` on `CLAUDE_LANES=1` hosts, mirroring the
`kk_mac_local` try-first pattern (chosen over the opencode
LANE_PROFILES pattern — that map resolves lane→agent-profile inside
`start_opencode_lane`; this feature is executor routing stamped at
queue/claim time, which is the kk_mac seam).

- `scripts/board/dispatch_repos.py` — `CLAUDE_TASK_CLASSES =
  {verify_only, repo_fix, report_triage}` + `claude_route(card)`.
  Admits only dispatch cards with nothing already routed (no
  executor/lane/host/target_host/runner/labels), no
  deploy/push/prod/cross-repo phrasing (`CLAUDE_SCOPE_RE`),
  single-repo scope (only the card's own repo may be named), and an
  admitted class — declared `action.task_class` must be in the set,
  else inferred: verify-only markers, fix markers **plus**
  verify-command evidence (`repo_fix` requires a runnable check —
  pytest/make test/verify_* fields), or report/triage markers.
- `scripts/board/board-api.py` — `_apply_classify_at_queue` tries
  `claude_route` after `kk_mac_route` and stamps
  `task_class`+`executor=claude`+`executor_source="queue"`.
  `do_claim` accepts claude+admitted-class task_class pairs and
  validates `executor_source` ("queue"/"claim", claude-only, never
  stamped onto a declared pin). `do_create` treats a bare claude
  task_class as the auto-route hint. `executor_source` is NOT in
  `ACTION_KEYS` — authors can't forge it; author executor edits drop
  it (lane_source semantics).
- `scripts/board/runner-agent.py` — `claude_lane_ready()` =
  CLAUDE_LANES=1 + claude-dispatch exists + cached `claude auth
  status` probe (no tokens). `executor_auto()` reads
  `executor_source`. Auto-routed claude cards a host can't serve
  fall back to normal lanes in `_claimable`, `executor_defer_reason`,
  `claim_executor`, `start_task` (try-first); declared
  `executor=claude` stays fail-closed. `claim_pass` backstop routes
  missed cards on ready hosts only, stamping `executor_source="claim"`.
  Latent fix: opencode lane hijack in `start_task` now requires
  executor unset — a claude pin can't be lane-hijacked.
- `scripts/devin/runner-tooling.manifest.json` — sha256 pins bumped
  for `runner_agent` + `dispatch_repos` (same-commit rule;
  `test_runner_tooling_contract` enforces).
- Tests — `ClaudeAutoRouteContractTest`/`ClaudeAutoRouteBoardTest`
  (executor contract), `ClaudeRouteUnitTest`/`ClaudeAutoRouteQueueTest`
  (queue-time classify), `ClaimPassClaudeRouteTest` (claim pass):
  every admitted class + every exclusion + no-fallback for declared
  claude + auto fallback on unready hosts.

## Result

- Verify command: `python3 -m pytest
  tests/board/test_executor_contract.py
  tests/board/test_runner_agent_lane.py -q` → **163 passed, 17
  subtests passed** (pytest 9.2.0 in `/tmp/pytest-venv`
  `--system-site-packages`; host python3.14 is PEP-668 managed).
- `tests/board/test_queue_time_classify.py` and
  `test_runner_tooling_contract.py` pass.
- Full `tests/board` sweep: 1103 passed, 12 failed — all 12
  reproduce identically on base HEAD (verified via stash): missing
  generated `board2/index.html` (2), close-out test gate needs
  system `python3 -m pytest` which PEP-668 blocks (6), host disk
  1616MB < 2048MB claim floor (4). Zero regressions from this diff.
- SSOT trail: `docs/ssot/jobs/board/2026-11-26-claude-bounded-auto-route.yml`.

## How to verify

```
/tmp/pytest-venv/bin/python -m pytest \
  tests/board/test_executor_contract.py \
  tests/board/test_runner_agent_lane.py -q
python3 -m unittest tests.board.test_queue_time_classify \
  tests.board.test_runner_tooling_contract
```

Manual: queue a card whose spec says "verify-only: confirm X without
modifying code" → board-api stamps `executor=claude,
task_class=verify_only, executor_source=queue` + comms. On a
CLAUDE_LANES=0 host the same card claims as a normal dispatch.

lessons:
- runner-tooling.manifest.json pins sha256 of runner-agent.py and dispatch_repos.py — ANY edit to those files must bump the pin in the same commit or test_runner_tooling_contract fails and sync-runner-tools.sh refuses the deploy.
- Host python3.14 is PEP-668 externally-managed: `pip install pytest` fails; use `python3 -m venv --system-site-packages /tmp/pytest-venv && /tmp/pytest-venv/bin/pip install pytest` to honor `python3 -m pytest` verify commands.
- 12 tests/board failures on this host are environmental, not code: missing generated stacks/web/public/apps/board2/index.html, close-out gate needing system pytest, and disk headroom 1616MB < 2048MB claim floor — verify against base via `git stash` before chasing them.
- board-api ACTION_KEYS is the author-writable whitelist: fields not in it (like the new executor_source) cannot be forged at create; pair that with explicit pop-on-author-edit sites (do_card_set, do_create respawn) to keep classifier provenance honest.
