# dispatch-outcome — devin-executor-model-routing (attempt 4, tony-omen)

## What happened

The prior run (tony-macbook, 2026-11-24 08:08, branch
`dispatch/20261124-080849-fix-the-executor-model-id-mism`) implemented the
full executor-aware fix but auto-merge failed with content conflicts in
`scripts/board/kanban-dispatch.py` and `scripts/devin/runner-tooling.manifest.json`.
This run merged that pushed branch into current master and resolved both
conflicts, then added the missing mocked-CLI preflight test the spec
required.

## Conflict resolutions

- `kanban-dispatch.py` — master had since added `lane_source` provenance
  stamping for classifier output; the branch replaced the raw
  `LANE_MODELS[lane]` litellm pick with `dr.lane_model(lane, "devin")`.
  Resolution keeps BOTH: `lane_source` stamp + executor-aware pick.
- `runner-tooling.manifest.json` — both sides moved pinned sources.
  Pins recomputed as sha256 of the MERGED files:
  runner-agent.py `35d284ec…`, dispatch_repos.py `ff858dba…`;
  devin-dispatch.sh pin `384680d4…` already matched merged content.

## What the change does (inherited from prior branch + verified here)

- `dispatch_repos.py`: `LANE_MODELS` keeps litellm/* aliases (opencode/
  proxy executor only); new `DEVIN_LANE_MODELS` holds devin-native ids —
  `free_lane -> swe-2-flash-medium` (confirmed present in live
  `devin models list`, cost_tier Free). `paid_frontier` deliberately has
  NO devin pick — paid route stays gated on explicit budget approval.
  New `model_valid_for_executor()` + `lane_model()` helpers.
- `runner-agent.py`: vendored mirrors + rewired `start_task` (declared
  pin vs executor-aware lane pick; bad-namespace pins drop to executor
  default with a card comms note), `claim_pass` (persists the model the
  actual route uses), `_start_opencode_lane` (skips bare devin ids).
- `kanban-dispatch.py`: `start_pending` persists `dr.lane_model(lane,
  "devin")`; launch env drops models failing `model_valid_for_executor`.
- `board-api.py`: queue-time classification no longer persists a
  lane-derived `action.model` (executor unknown at queue time).
- `devin-dispatch.sh`: `_model_preflight` validates `$DISPATCH_MODEL`
  against `devin models list` (`--format json` + text-table fallback)
  BEFORE systemd-run — rc 2 reject, rc 3 unverifiable, billable tiers
  pass with a stderr note; `DEVIN_MODEL_PREFLIGHT=0` escape hatch.

## Added this run

- `tests/devin/test_model_preflight.py` — 7 tests driving the real
  script against a mocked `devin` binary: litellm alias -> exit 2 before
  repo resolution (no worktree/task dir), listed free id -> passes gate,
  paid id -> passes with billable note, broken CLI -> exit 3,
  `DEVIN_MODEL_PREFLIGHT=0` bypass works.
- `docs/ssot/jobs/infrastructure/2026-11-24-executor-aware-model-routing.yml`
  — runbook/trail for the change.

## Verified

- `pytest tests/devin/test_model_preflight.py` — 7 passed.
- `pytest tests/board/test_runner_agent_lane.py
  test_runner_tooling_contract.py test_queue_time_classify.py
  test_executor_contract.py tests/devin/test_unit_exit_status.py` —
  175 passed, 17 subtests (9m25s).
- `py_compile` on all touched .py, `bash -n` on devin-dispatch.sh,
  manifest JSON parses, SSOT yaml validates (pre-commit gate passed).
- Live `devin models list --format json` on tony-omen confirms
  `swe-2-flash-medium` is a real Free-tier id.

## Notes / leftovers

- Pre-existing master bug spotted (NOT fixed, out of scope): runner-agent
  `start_task` has a duplicated `nlm_batch` dispatch block (~line 3618) —
  second copy unreachable dead code.
- `docs/ssot/ssot.dev-system.assessment.yml` shows an unrelated
  hook-generated modification in the worktree — left untouched.
- Card `verified: false` / `review_kind: verify` — merge-sweep + review
  will confirm; runner-agent redeploy to fleet hosts happens via
  sync-runner-tools on next repo-sync (manifest pins now match).

lessons:
- Dispatch branches that sit unmerged rot fast: master gained lane_source stamping within hours, producing the exact conflict that killed the auto-merge. Merging the pushed prior branch into a fresh worktree and resolving by hand is the reliable salvage path.
- runner-tooling.manifest.json pins must be sha256 of the MERGED file content, not either parent's pin — recompute after every conflict resolution.
- `devin models list --format json` schema: families[].slug/aliases + variants[].model_uid/cost_tier — mock that shape for CLI tests; plain `models list` text table is the fallback path.
- Paid-lane gating pattern that worked: keep the lane in LANE_MODELS (opencode/proxy) but omit it from DEVIN_LANE_MODELS so lane_model() returns '' -> executor default, never a silent billable mapping.
