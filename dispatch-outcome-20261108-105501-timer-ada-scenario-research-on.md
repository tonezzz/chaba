# Dispatch outcome — timer-alert-idc03-ada-scenario-research (2nd pass)

## What was found

The card was already resolved by the sibling dispatch ~1h earlier
(`dispatch-outcome-20261108-103641-*.md`): the Nov-02 exit-code was stale
deployed wrapper+unit plus a zombie ada-dev; files refreshed 10:34,
live-verified 10:48. This session **re-verified** that state on idc03:

- `ada-scenario-research.service` is NOT in `list-units --failed`;
  deployed `scenario-suite-run.sh` + unit md5-identical to repo HEAD.
- Next fire Mon 2026-11-09 05:55; a completed failing run now exits 0
  (OPS-0581 contract live), and a quota-dead provider skips cleanly via
  ExecCondition — both by design.

## New finding (sibling unit)

`ada-scenario-smoke.service` failed `result=exit-code` at **10:37 today**
— a *completed* 43-scenario run that exited 1 because the smoke/full
quadlets run `scenario-report.py` directly and bypass
`scenario-suite-run.sh` — the last residual finding-reporters under the
OPS-0581 contract (listed in `docs/kb/timer-expectations.md`, unit in
`known_failed`). Trigger: the bench LiteLLM virtual key crossed its
$2 cap at ~10:33 mid-run (every turn 422 `budget_exceeded`, OpenRouter
fallback 404 → ~20 fails, outage sentinel → skip-quota). Also observed:
~9 `TimeoutStartSec` SIGKILLs Nov 07-08 — the 45-min truncation already
carded as `ada-scenario-smoke-timeout-truncation` (ADA-1106).

## What changed

- **`stacks/services/ada-scenario-runner/container-suite-run.sh`** (new) —
  container ENTRYPOINT shim applying the OPS-0581 contract: greps
  scenario-report.py's final `N scenarios:` marker, exit-1-with-marker → 0,
  crash-without-marker stays nonzero. Verified locally: completed-fail→0,
  crash→1, clean→0. bash+coreutils confirmed in `python:3.12-slim`.
- **`Containerfile`** — COPYs the shim, ENTRYPOINT now the shim; covers
  smoke and full (shared image).
- **`docs/kb/timer-expectations.md`** — residual list updated: smoke/full
  marked converted-in-stack, effective on next `install.sh` rebuild.
- Commit `1f3b48b22` on `dispatch/20261108-105501-timer-ada-scenario-research-on`.
- **Carded** `ada-scenario-quadlets-exit-contract` (ADA-1171): deploy =
  run `install.sh` on idc03 (image rebuild); also notes the provider-gate
  blind spot (bench-key cap invisible when other lanes' 200s refute REST
  dunning — gate verdicted ok at 10:00 AND 11:00 while the bench key was
  dead).
- Job trail: `docs/ssot/jobs/ada/2026-11-08-ada-scenario-smoke-quadlet-exit-contract.yml`.

## NOT done / pending

- **Deploy intentionally skipped** (dispatch rail: no deploys unless the
  task says so). Until `install.sh` rebuilds the image, completed-fail
  smoke runs still exit 1 — suppressed from sentinel by `known_failed`.
- Bench $2/30d cap still exhausted → hourly smoke keeps mass-failing
  (recorded as infra/skip-quota in reports, not silent).

## How to verify

- `ssh idc03 systemctl --user list-timers | grep research` → next Mon 05:55;
  `journalctl --user -u ada-scenario-research.service --since '2026-11-09'`
  → completed run exits 0 or clean exec-condition skip.
- After install.sh on idc03:
  `journalctl --user -u ada-scenario-smoke.service --since <next-hour>` →
  "suite completed with failing scenarios" + no `Failed result`.
