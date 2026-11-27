# Dispatch outcome — kanban-free-lane-routing-contract (KNB-0244)

DECISION 2026-11-26 Tony: adopt — implement the dispatch-envelope part of
the free_lane routing contract: stage `action.lane_envelope` at queue
time so free_lane cards stop holding on "lane_envelope is not staged";
keep the `executor=devin` pin escape hatch; regression tests for both
paths.

## What changed

**Queue-time staging (the feature)**

- `scripts/board/dispatch_repos.py` — new `lane_envelope_plan(card,
  lane, repo_root)` + constants (`LANE_PROFILES`, `STAGED_LANE_HOST=idc02`,
  `STAGED_LANE_STAGE=S3`, `STAGED_LANE_CLASSES`, `STAGED_LANE_PROFILES`
  = mirror of runner-agent.S3_STAGED_PROFILES, `STAGED_LANE_ROOTS` =
  mirror of lane_gate.STAGE_ALLOWED_ROOTS[S3]). The planner derives the
  complete envelope from the card + the task profile's own
  `profile.yml` (verifier, artifact schema, model allowlist, stage/class
  ceilings, escalation, rollback all read live so a profile edit can't
  drift the staged copy). Model precedence is identical to
  `runner-agent._start_opencode_lane` (action.model > LANE_MODELS[lane]
  > profile default) so `env.model` always equals what the claim
  resolves. Fail-safe: returns None on author-staged envelope, declared
  executor, unmapped/manual lane, foreign target_host/host/subject_host
  pin, non-chaba repo, non-admitted profile, unadmitted task_class,
  artifact outside profile dirs, unresolvable model, or mutating intent
  (`KK_MAC_MUTATING_RE`) — the card keeps the existing hold.
- `scripts/board/board-api.py` — `_apply_classify_at_queue` now calls
  the planner on every queue path (`/action do=queue`, report-page
  respawn, `do_create`+queue) when `type=dispatch` with no declared
  executor/lane_envelope. On success it merges
  `action={executor:opencode, agent_profile, task_class, artifact,
  target_host:idc02, lane_envelope}` and posts a "staged lane_envelope"
  comms line. `target_host` is pinned to idc02 at queue time — honest,
  since `prepare_profile_dispatch` only admits HOST==idc02 anyway.

**Devin-path guard (the escape hatch stays intact)**

- `scripts/board/kanban-dispatch.py` — `_verdict_reason` + the claim
  loop skip any queued card carrying `action.lane_envelope` when
  `executor` is unset (staged envelope = opencode-bound; this
  dispatcher only runs devin). `executor=devin` still claims.

**Contract drift fixes (required for the staged model to match)**

- `scripts/board/runner-agent.py` — vendored `LANE_MODELS["free_lane"]`
  still said `litellm/gemini-3.5-flash-lite` after the OPS-1363 repoint
  to `litellm/agent-local`; fixed. A stale runner resolving the old
  model would fail the envelope's expected-match at claim.
- `evals/opencode-lane/profiles/ops-readonly/profile.yml` —
  `model.allowed` gained `litellm/agent-local`.
- `scripts/devin/runner-tooling.manifest.json` — sha256 pins bumped for
  `runner-agent.py` + `dispatch_repos.py` (same-commit contract).

**Tests**

- `tests/board/test_lane_envelope_staging.py` (NEW, 23 tests) — the
  staged envelope passes `lane_gate.lint_envelope`,
  `opencode_profiles.check_envelope`, AND
  `runner-agent.prepare_profile_dispatch` end-to-end on idc02;
  `claimable()`/`executor_defer_reason()` clear on an OPENCODE_LANES
  host and hold on foreign hosts; devin-pin path untouched; escape
  cases: mutating intent, foreign target_host/host/subject_host,
  non-chaba repo, non-staged profile, author-staged envelope, declared
  executor=opencode, unadmitted task_class/artifact, missing profile
  yaml. Lane-table lockstep test pins LANE_MODELS/DEVIN_LANE_MODELS/
  LANE_PROFILES across dispatch_repos ↔ runner-agent.
- `tests/board/test_queue_starvation.py` — kanban-dispatch steal-guard
  test (staged-envelope card skipped, devin pin still claims).
- `tests/board/test_queue_time_classify.py` — `test_lane_pin_not_rerouted`
  updated: a lane-pinned free_lane card now legitimately gets
  executor=opencode from staging (asserts != kk_mac_local, == opencode).
- `tests/devnest/test_lane_gate.py` — fixed PRE-EXISTING stale
  `test_quota_exceeded` (S1 quota raised 3→15 by OPS-1363 without
  updating the fixture; now derives done from STAGES).
- `tests/devnest/test_opencode_profiles.py` — fixed PRE-EXISTING stale
  job-count assertion (7→9 p*.yaml envelopes after OPS-1363 additions).

## Envelope shape staged (ops-readonly / free_lane example)

```yaml
lane_envelope:
  id: <card-id>            # prepare_profile_dispatch overwrites with task id
  card: <card-id>
  task_class: report       # or declared read_only
  stage: S3
  target_host: idc02
  executor: opencode
  profile: ops-readonly
  model: litellm/agent-local
  provider: litellm
  unattended: true
  mcp_allowlist: []
  allowed_paths: [evals/opencode-lane/out/, reports/]
  artifact: {path: evals/opencode-lane/out/<card-slug>.json,
             schema: <profile artifact.schema verbatim>}
  verifier: {type: held_out_py,
             ref: evals/opencode-lane/profiles/ops-readonly/fixture/verify.py}
  escalation: {on_fail: manual, allowed_on_fail: [manual], max_retries: 1}
  rollback: {kind: none}
  heartbeat: {required: true, stale_s: 300}
  timeout_s: 420
```

plus `action.{executor:opencode, agent_profile:ops-readonly,
task_class, artifact, target_host:idc02}`.

## Result / verification

- `pytest tests/board/test_lane_envelope_staging.py` — 23 passed.
- `pytest tests/devnest/` — 424 passed (with OPENCODE_LANES unset; the
  lane env var on idc02 legitimately changes one env-gate test's
  assumptions — pre-existing env sensitivity, unrelated).
- `pytest tests/board/` full suite — re-run in progress at write time;
  prior run: 1099 passed, 4 failed — all four addressed (2 were
  missing generated board2 assets, fixed by running
  `scripts/render-board2.py`; 1 updated expectation; 1 manifest pin).
- CI lane checks: `python3 -m compileall scripts/` clean;
  `sync-opencode-models.py --check` exits 0 (`agent-local` shows as
  informational route_not_registered — the hourly sync registers it);
  repo-lint pytest subset 37 passed.
- Trail: `docs/ssot/jobs/devnest/2026-11-26-free-lane-envelope-staging.yml`.

## Deploy note (important for the done-condition "a free_lane card
claims without manual pinning")

The claim path needs BOTH sides deployed: board-api (idc03 served
checkout, post-merge) stages `model=litellm/agent-local` from canonical
dispatch_repos; the claiming runner resolves the same pick from its
INSTALLED runner-agent. Until `sync-runner-tools.sh` installs the new
runner-agent on idc02 (manifest pins already bumped so fleet-health
will flag/repair drift), a staged card claimed by the stale runner
resolves `gemini-3.5-flash-lite` and fails the envelope expected-match
— burning an attempt. Sequence: merge → sync runner tools fleet-wide
→ free_lane cards claim cleanly. Cards queued before the merge keep
the hold until re-queued (`/action do=queue` re-runs staging).

## lessons:

- runner-agent.py and dispatch_repos.py are BOTH sha256-pinned single-file tools (scripts/devin/runner-tooling.manifest.json) — any edit to either must bump its pin in the same commit or test_runner_tooling_contract fails.
- runner-agent vendors copies of dispatch_repos tables (LANE_MODELS, LANE_PROFILES, model_valid_for_executor) — queue-time code in dispatch_repos must mirror the runner's claim-time resolution exactly or the staged envelope fails expected-match at claim.
- prepare_profile_dispatch hard-requires HOST==idc02 + stage S3 + profile in S3_STAGED_PROFILES — queue-time staging must pin target_host and positive-check the profile set, never guess.
- tests/devnest/test_lane_gate.py is env-sensitive: it assumes OPENCODE_LANES is unset — run devnest tests with `env -u OPENCODE_LANES` on lane-enabled hosts like idc02.
- tests/board/test_control_pane_projection.py needs generated stacks/web/public/apps/board2/{index.html,cards.json} — run scripts/render-board2.py in fresh worktrees before the board suite.
