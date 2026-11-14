# Dispatch outcome — S3 dispatch hardening (OPS-0121)

Card: `opencode-lane-s3-dispatch-hardening` — runner `tony-omen`,
branch `dispatch/20261114-102801-found-during-first-s3-card-pil`.
All four findings from the first S3 card pilots (2026-11-14,
`ops-event-plane-split-brain-audit` + `ada-docs-search-drift`) are
implemented and tested. No push, no deploy, no production changes.

## What changed

### 1. Timeout evidence loss — `scripts/devnest/opencode_profiles.py`

`run_profile_process` catch-block for `subprocess.TimeoutExpired` now
writes `e.stdout` → `<run_dir>/events.jsonl` and `e.stderr` →
`<run_dir>/stderr.log` (normalized via `_partial_text` — POSIX returns
bytes even under `text=True`) before re-raising, so `cmd_run` still
records `exit_code=-2` / `failure_reason=timeout`. Supervised observer
path unchanged (it already streamed to files).

### 2. Installed runner-agent drift gate — `scripts/board/runner-agent.py`

- `_self_ref()` resolves the repo reference copy
  (`DISPATCH_REPOS_DIR`/`repos.conf`/`~/CascadeProjects/chaba` +
  `scripts/board/runner-agent.py`), shared with `_self_update()`.
- `self_stale_reason()` byte-compares `Path(__file__).resolve()` against
  the reference — **only when the running file is the deployed snapshot
  `~/.local/bin/runner-agent`** (same predicate as `_self_update`).
  In-checkout/dev/test execution is never gated. Missing reference or
  self-reference also does not gate.
- `_claimable()` returns the stale reason before any routing decision —
  a drifted agent claims nothing rather than routing S3 cards to the
  wrong executor (the Oct-26 tony-dell binary lacked `target_host`
  gating and claimed idc02-pinned cards into generic dispatch, which
  failed in 518 ms).
- `claim_pass()` surfaces the decline via `note_defer(card, "stale",
  reason)`; the reason tells operators to redeploy with
  `scp scripts/board/runner-agent.py <host>:~/.local/bin/runner-agent`.

### 3. Self-contained lane env — `scripts/board/runner-agent.py`

`launch_profile_dispatch`'s transient `devin-task-*` unit shell now
starts with `export OPENCODE_LANES=1;`. Those units do not inherit
`runner-agent.service`'s drop-in env — the idc02 pilot failed
`env_gate` until the variable was planted in the systemd user manager.
The contract is now carried by the unit itself.

### 4. Bounded retries for free-model variance —
`scripts/devnest/opencode_profiles.py` (+ closeout in `runner-agent.py`)

- `cmd_run` consumes `escalation.max_retries` from the frozen envelope
  (unattended only; supervised stays single-attempt), hard-capped by
  `MAX_RUN_ATTEMPTS = 4`.
- Each attempt runs `_run_attempt(...)` — render/execute/audit/verify/
  metric/run.json — into its own run dir (`<job>-<ts>` then `-r<n>`),
  with `attempt`/`retries` recorded in the ledger.
- Retryable set: `missing_artifact`, `unverified_exit`, `timeout`,
  `executor_error`. Contract violations (`mutating_command`,
  `verifier_peek`, `scope_violation`, `tool_denial`,
  `independent_review_preparation_error`) never retry.
- Retries set `_retry_hint` → a deterministic `RETRY_HINT` block
  appended in `build_prompt` restating the artifact contract (the
  nemotron-ultra variance class: malformed citations / wrong schema).
  `_`-prefixed keys are excluded from `manifest["envelope"]`, so the
  frozen envelope stays intact.
- `escalated` is computed after `failure_reason` is known: only a
  terminal failure (last allowed attempt, or a non-retryable reason)
  escalates — an intermediate failure is a retry in progress.
- `finish_profile_dispatch` accepts the derived retry-hint prompt as a
  second allowed prompt form (both derived from the frozen envelope, so
  admission still binds the text).

## Tests added

- `tests/devnest/test_opencode_profiles.py`:
  `test_nonobserver_timeout_preserves_partial_output`; `RetryAttempts`
  class — retryable-failure rerun with schema hint and pass,
  contract-violation no-retry + immediate escalation, zero-budget
  single-attempt, `_retry_hint` kept out of the frozen manifest.
- `tests/board/test_executor_contract.py`: `SelfStaleGateTest` (drift
  declines, matching claims, in-place runs never gated, missing
  reference doesn't gate) and `StagedDispatchShellTest`
  (`OPENCODE_LANES=1` in the unit shell).

## Verification

- `python3 -m unittest tests.devnest.test_opencode_profiles` —
  83 tests, OK
- `python3 -m unittest tests.board.test_executor_contract` —
  83 tests, OK
- Board lane/push/queue suites (129 tests incl.
  `test_runner_agent_lane`, `test_runner_push_guard`,
  `test_queue_time_classify`) — OK after scoping the stale gate to the
  deployed snapshot
- `python3 -m py_compile scripts/devnest/opencode_profiles.py
  scripts/board/runner-agent.py` — OK

## Result / decision notes

- Fleet drift is handled fail-closed by the version gate rather than a
  new deploy pipeline: a stale installed agent defers claims with an
  operator-visible reason instead of misrouting. The companion gap —
  no automated deploy of `~/.local/bin/runner-agent` — is mitigated but
  the scp-redeploy hint remains the operator path; an automated sync
  mechanism would be a separate card if wanted.
- Envelopes with `max_retries: 0` (like the pilot card) remain
  single-attempt by design; retry only engages when the envelope
  declares budget. `ssot-research/profile.yml` already declares
  `max_retries: 1`; staged dispatch envelopes may still carry `0`.
- Retried jobs land the final attempt's evidence for closeout;
  intermediate attempts remain on disk and in the ledger (the
  qualification-ledger dedup check at closeout counts the final metric
  exactly once).

## Remaining limitations

- Deployed snapshots on other hosts (tony-dell) still carry the old
  binary until redeployed — they will now defer rather than misclaim,
  which is the intended fail-closed behavior.
- Retries re-render the same profile config; there is no per-attempt
  model downgrade/escalation — the retry hint is the only prompt delta.
