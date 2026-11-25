# Dispatch outcome — runner-load-cap-per-claim-type (attempt 2)

## What I found

The card's core request was **already implemented and merged on
2026-11-08** in commit `e353fc8359` ("OPS-1182 + KNB-1183: per-type
load cap and host-gate card visibility"), the same day the card was
captured:

- `overloaded(pc)` in `scripts/board/runner-agent.py` takes a
  per-call ceiling; `SCRIPT_MAX_LOAD_PC`
  (`RUNNER_SCRIPT_MAX_LOAD_PC`, default **2.0**) gives script claims
  a higher cap than the strict `RUNNER_MAX_LOAD_PC` (0.85 on idc03).
- `claim_pass` degrades to a **script-only pass** under partial
  overload (strict cap exceeded, script ceiling still ok);
  dispatch/container claims still defer — the expensive classes keep
  the strict cap, per spec.
- `_note_capacity_skip` exempts script cards from the hostgate defer
  note; `executor=script` dispatch cards resolve to `typ=="script"`
  in `_claimable`, so they are covered too.
- `kanban-dispatch.py` needs no change — it only claims
  `action.type=dispatch`, so its load gate already only guards
  heavyweight work.

## The gap I fixed

`verdict_pass` (the `/ready` projection behind /queue's
eligible/blocked view) did **not** mirror the script exception: under
partial overload it reported *every* queued card — including script
cards `claim_pass` was actively claiming — as `host overloaded`
blocked. Same OPS-1107 inconsistency class the function's own comment
warns about, inverted.

## Changes (commit `f51df8c640` on the dispatch branch)

- `scripts/board/runner-agent.py` — `verdict_pass` exempts
  `typ == "script"` from the overload capacity reason when load is
  still under `SCRIPT_MAX_LOAD_PC`. Non-load capacity reasons
  (runner cap, rate-limit cooldown, kill switch, disk floor) still
  block all claim types.
- `tests/board/test_runner_agent_lane.py` — new
  `VerdictPassLoadTest`, 3 cases: partial overload → script ok /
  dispatch blocked; full overload → both blocked; disk-floor reason
  → script blocked too.
- `scripts/devin/runner-tooling.manifest.json` — `runner_agent`
  sha256 pin bumped in the same commit (tooling-contract test
  enforces pin == source).
- `docs/ssot/jobs/board/2026-11-25-runner-load-cap-per-claim-type.yml`
  — job/runbook trail.

## Verification

- `python3 -m unittest tests.board.test_runner_agent_lane
  tests.board.test_runner_tooling_contract` — **46 tests OK**.
- Full `tests/board/test_runner*.py` discovery — 192 tests, the only
  failure was the pin-hash contract, fixed by the manifest bump
  (re-run of the two affected files green).
- Prior attempt's failure ("no exit record — unit not-found") was a
  dispatch-infra issue, not a code problem; this run completed
  normally.

## Deploy note

No manual step needed: installed runner-agents self-update from
origin/master (`_self_update` / `sync-runner-tools.sh`) once this
merges; the fleet drift flag clears on the next sync tick.

## lessons:

- Check `git log -S <symbol>` before implementing — this card's spec
  was verbatim the OPS-1182 commit message; the work predated the
  retry by 17 days.
- runner-agent.py is pin-gated: any source edit MUST bump
  `runner_agent.sha256` in `scripts/devin/runner-tooling.manifest.json`
  in the same commit or `test_runner_tooling_contract` fails.
- When a pass-level gate gets a per-type exception, audit EVERY
  consumer of the shared reason (`_capacity_reason` feeds both
  claim_pass and verdict_pass) — the /ready projection drifted from
  claim behavior.
