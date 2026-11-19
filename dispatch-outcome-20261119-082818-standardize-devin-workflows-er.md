# Dispatch outcome — Standardize Devin workflows & error handling (run 2)

**Card:** `standardize-devin-workflows-error-handli-e19df2` (DEV-0253)
**Result:** no new work needed — this session is a zombie restart
(OPS-1071: "claim committed but the response was lost", restarted as
devin-task-20261119-082818 on idc02). The deliverables from the first
run (task 081342, ~40 min earlier) already landed, merged, and
verified. This run's contribution is an independent spot-check of that
work against the live code.

## State found

- Live card: `column: review`, `action.status: done`, `verified: true`.
- First run's branch `dispatch/20261119-081342-…` auto-merged to
  origin/master at 08:20 (merge `3eb58a54`) after the test gate passed;
  worktree GC'd. Deliverables:
  - `docs/kb/devin-error-handling-standard.md` — lane-by-lane audit
    table + distilled 10-rule standard + honest gaps section.
  - `docs/ssot/ssot.procedures.yml` — entries `devin-error-standard`
    (line 145) and `session-blocked-protocol` (line 146), pointer-style
    per the index contract.
  - `AGENTS.md` — "Devin workflow & error-handling standard" duty at
    line 164 (lane-author rules + session-side rails contract).
  - `docs/ssot/jobs/board/2026-11-19-devin-workflow-error-standard.yml`
    — job record.

## Independent spot-check (this session)

Read the audited sources directly; every sampled claim in the kb doc
matches the code:

- Retry ledger: `runner-agent.py` — `retry-ledger.json`, exponential
  backoff `1800·2ⁿ⁻¹` capped 6h, `RUNNER_RETRY_MAX=3` host hold;
  `RETRY_REARM_TEXTS` = deliberate human verbs only, producer re-queues
  and `attempts` bumps deliberately excluded (Nov 8–9 flood driver).
- Evidence-forward retry: `RETRY_RAILS` in `kanban-dispatch.py`
  injects `action.last_failure` into the next session prompt.
- Blocked≠failed: `scripts/devin/job-run.sh` exit-42/`NEEDS-INPUT:`/
  needs-input.txt contract confirmed; board `/request` +
  `$TASK_DIR/answers.jsonl` is my own live rails.
- Advisory-never-blocks: `_publish` docstring "a dead api never blocks
  the claim loop"; `lesson_primer` wrapped "advisory — never block a
  run".
- Claim-time gates: push-credential probe (`push:<repo>` label or live
  `git push --dry-run`, ADA-0673), GPU VRAM preflight (refuse when need
  exceeds total — "fix the spec"), labels/load/quiet-hours/kill-switch,
  waiting-cards R3/R4 never-claim, fail-closed unknown-executor
  ("don't guess a route").
- Nothing unproven destroyed: `dispatch-wt-sweep.py` salvage-pushes
  doomed heads to `refs/heads/wip/dispatch/<tid>` and KEEPs trees it
  can't prove safe.
- Verified gate: merge-sweep docstring — exit evidence ∧ produced-work
  ∧ `auto_done_when`, each leg pass/fail/unverifiable; `verified:
  false` = checked-failed (requeue), withheld = hold for human.
- YAML hygiene: both edited YAML files parse clean.

The doc's own gaps section is also accurate — the runner-agent
drift-defers filling this card's comms are the vendored-twin deploy
weakness it names.

## Nothing else done

- No code/doc changes — duplicating the standard would fork it.
- Card `awaiting_action: true` is stale residue of the earlier defer
  streak; the card sits in review for Tony's close per the normal
  verified-drain path — left for the sweep/human, not flipped from a
  dispatch worktree.

## How to verify

- `git log --oneline origin/master | grep -i error-standard` →
  `e307d7ccee` + merge `3eb58a54`.
- Live card API: `column=review, action.status=done, verified=true`.
- `grep -n 'devin-error-standard' docs/ssot/ssot.procedures.yml` → 145;
  `grep -n 'error-handling standard' AGENTS.md` → 164.

lessons:
- Zombie restarts (OPS-1071) produce duplicate sessions — before doing work, check the card's live action.status/verified and the outcome-file namespace for a same-card sibling run; a 40-minute-old merge means "verify and report", not "redo".
- The correct output of a duplicate dispatch is itself a demonstration of the standard: fail-loud-with-evidence = comms note explaining the state; finished≠verified = the first run earned verified only via the merge gate, not by exiting 0.
