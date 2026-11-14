# Dispatch outcome — S3 dispatch hardening (OPS-0121), verification pass

Card: `opencode-lane-s3-dispatch-hardening` — runner `tony-omen`,
branch `dispatch/20261114-121825-found-during-first-s3-card-pil`.

## Finding: the work was already merged before this session ran

The 10:28 dispatch (`dispatch/20261114-102801-found-during-first-s3-card-pil`,
outcome commit `dc8dee1851`, follow-up `4edd6031f2`) implemented all four
spec items, and its branch is already an ancestor of `origin/master`
(`a5e75cd3be` — this worktree's HEAD == origin/master). This re-dispatch
fired because the card stayed `doing`/`running` after the merge — a
card-state closeout lag, not missing code. This session therefore verified
the merged implementation instead of re-implementing it.

## Verified in this worktree

1. **Timeout evidence loss** — `run_profile_process`
   (`scripts/devnest/opencode_profiles.py` ~L843) catches
   `subprocess.TimeoutExpired`, writes `e.stdout`→`events.jsonl` and
   `e.stderr`→`stderr.log` via `_partial_text` (bytes-under-POSIX
   normalize), then re-raises so `cmd_run` records
   `exit_code=-2`/`timeout`. Evidence now survives a killed run.
2. **Fleet drift gate** — `self_stale_reason()` +
   `_self_ref()` (`runner-agent.py` ~L1081) byte-compares
   `~/.local/bin/runner-agent` against the repo reference and
   `_claimable()` returns the stale reason before any routing decision;
   `claim_pass` surfaces it via `note_defer(card,"stale",reason)` with an
   scp-redeploy hint. Scoped to the deployed snapshot only — in-checkout
   runs are never gated. Fail-closed, as spec'd ("version check in
   claimable()" option).
3. **Self-contained lane env** — `launch_profile_dispatch`'s transient
   `devin-task-*` unit shell exports `OPENCODE_LANES=1`
   (`runner-agent.py` ~L2142), so `admit()`'s env_gate no longer depends
   on manager-level env or `runner-agent.service` drop-ins.
4. **Free-model variance** — `cmd_run` consumes
   `escalation.max_retries` (ceiling-checked vs the profile at
   admission, hard cap `MAX_RUN_ATTEMPTS=4`, unattended only) through
   `_run_attempt`; retryable set is outcome failures
   (`missing_artifact`, `unverified_exit`, `timeout`, `executor_error`),
   contract violations escalate immediately. Retries append the
   deterministic `RETRY_HINT` block in `build_prompt`, and
   `finish_profile_dispatch` accepts both prompt forms so admission
   binding holds. `ssot-research/profile.yml` already declares
   `max_retries: 1`; envelopes carrying `0` stay single-attempt by
   design.

## Tests run here

- `python3 -m unittest tests.devnest.test_opencode_profiles` — 83 tests, OK
- `python3 -m unittest tests.board.test_executor_contract` — 83 tests, OK
  (covers `SelfStaleGateTest`, `StagedDispatchShellTest`)

## Residual / notes for closeout

- **tony-dell's Oct-26 binary** still lacks `self_stale_reason` *and*
  `_self_update` — the gate only protects hosts already on the new
  track, so tony-dell needs one manual bootstrap:
  `scp scripts/board/runner-agent.py tony-dell:~/.local/bin/runner-agent`.
  `runner-fleet-health` (via `scripts/ada/kanban-sync.sh`) is the
  existing automation that cards this drift; no new mechanism needed.
- Card still shows `doing`/`running` — it can move to done/review on
  the strength of the merged commits + this verification.
- No code changes produced by this session; nothing to push.
