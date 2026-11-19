# Dispatch outcome — ada-card-runner (ADA-0042), attempt 2

Branch: `dispatch/20261119-162739-pieces-1-card-pick-strategy-se`
Commit: `094c25b529` (unpushed — merge-sweep/dispatch close-out owns landing)
Host/executor: tony-omen, devin

## Prior failure (attempt 1) — root cause and fix

idc02's runner-agent claimed the card (kw-classified `free_lane`, spec
contains "launch") and `start_opencode_lane` held it:
`OpenCode admission requires a complete action.lane_envelope; unstaged
dispatch is held`. The claim **burned an attempt** (fail 1/3 backoff)
even though the ineligibility was deterministic — staged admission
(2026-11-09, OPS-1255) makes the envelope mandatory for every
opencode-lane start, so an unstaged card could never succeed.

Fix (DEV-0253 "gate at claim, not mid-run"): `scripts/board/runner-agent.py`
now holds such cards **at claim** — `_claimable` returns a defer reason
and `executor_defer_reason` surfaces it on the board ("stays queued for a
staged envelope or an executor=devin pin"). Covers
`executor=opencode`-declared cards and executor-unset cards whose lane
resolves to an opencode route (`lane ∈ LANE_MODELS` + profile). Envelope-
carrying, `executor=devin`-pinned, `OPENCODE_LANES=0`, and non-LANE_MODELS
lanes are all unaffected — verified by test.

## Spec piece 4 — eval loop (the missing piece)

Pieces 1–3 were already merged (PRs #159/#163) and the pilot ran
(AUD-0060, 2026-11-12). `--lifecycle` was single-shot; now:

- `--attempts N` (1..3, default 2): retries resume the SAME opencode
  session via `opencode run --continue` with the eval evidence as the
  message — evidence rides the next attempt, never a cold restart.
- Eval per attempt: changes-present → git-state normalize →
  **repo-validate** (`diff --check` + syntax on touched files: py
  `compile()` [no `__pycache__`], sh `bash -n`, yml/json parse) → the
  card's declared verifier.
- `--ci-wait` (default 120s): polls the PR `statusCheckRollup` after
  `gh pr create`; result rides the finish note (`pass | fail: <check> |
  pending | skipped | unknown`). Pending is reported, never a blocker —
  merge stays the human/merge-sweep gate.

## Files changed

- `scripts/board/card-run.py` — eval loop + helpers
  (`_porcelain_paths`, `_validate_changes`, `_evaluate_attempt`,
  `_ci_wait`, `RETRY_MSG`) + `--attempts`/`--ci-wait`
- `scripts/board/runner-agent.py` — unstaged-opencode claim hold
  (`_claimable` + `executor_defer_reason`)
- `tests/board/test_card_run.py` — NEW, 20 tests
- `tests/board/test_executor_contract.py` — +9 hold tests; 2 existing
  opencode-claimable tests updated to carry `lane_envelope` (new contract)
- `tests/board/test_runner_agent_launchd.py` — oc-route serves test now
  requires envelope + asserts unstaged hold
- `docs/ssot/jobs/board/2026-11-19-ada-card-runner-eval-loop.yml` — job record

## Verification

- `pytest tests/board/test_card_run.py + UnstagedOpencodeHoldTest +
  ClaimableContractTest` — 36 pass
- `test_executor_contract.py` (full) — 115 pass
- `test_runner_agent_lane.py + test_queue_time_classify.py +
  test_claim_order.py` — 60 pass
- `test_runner_agent_launchd.py + test_runner_push_guard.py +
  test_queue_starvation.py` — 63 pass
- `test_runner_agent_reconcile.py + test_build_task_regressions.py` — 15 pass
- Smoke: `card-pick.py sweep|high-value --api idc03` live picks OK;
  `card-context.py ada-card-runner` renders the full pack
- `git diff --check` clean; pre-commit SSOT validation passed on commit

## Follow-ups noted (not done here)

- runner-agent.py is a single-file per-host deploy — the hold protects
  claims only where the repo copy is installed. The recurring
  "installed runner-agent drifted from repo" defer notes (this card's
  comms, up to 2026-11-18) mean several hosts are behind — fleet
  `scp scripts/board/runner-agent.py <host>:~/.local/bin/runner-agent`
  redeploy needed for fleet-wide effect.
- `docs/ssot/ssot.dev-system.assessment.yml` was regenerated in the
  worktree by the pre-commit assessment hook — left uncommitted
  (unrelated to this task).

lessons:
- free_lane-classified build cards route to the opencode lane on OPENCODE_LANES=1 hosts and burn an attempt per claim when no action.lane_envelope is staged — the fix is a claim-time hold, not card YAML edits.
- runner-agent.py claim-time gates must replicate start-time routing (lane→profile→envelope) or the card fails AFTER claim and the attempt ledger pays for it.
- `opencode run --continue` resumes the last session in the cwd — the cheap way to make retries carry evidence instead of cold-restarting.
- tests/board has slow fixture-heavy files (~10min): use `-k` class filters when iterating, full file for final verification.
- pre-commit regenerates docs/ssot/ssot.dev-system.assessment.yml — leave the stray diff unstaged in dispatch worktrees.
