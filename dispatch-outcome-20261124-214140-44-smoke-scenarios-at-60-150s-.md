# Dispatch outcome — ada-scenario-smoke-timeout-truncation

## What was found

- Smoke path: `ada-scenario-smoke.container` (TimeoutStartSec=2700) →
  `container-suite-run.sh` → `scenario-report.py --tier smoke` in the
  mounted ada-voice repo — strictly sequential, one ws session at a
  time, per-scenario MDDB reports to `ada-ha-scenario-reports`,
  `:8199` TCP lock shared with the weekly benchmark suites.
- The suite now has **47** `tier: smoke` scenarios (card estimated 44)
  at ~60-150s each + one retry → ~70-130min, well past the 45-min cap.
  Every hourly run was SIGTERM'd mid-tier; a-z ordering meant the tail
  never ran.
- The card's "python -u" cheap win is already covered:
  `PYTHONUNBUFFERED=1` is set in both quadlets and every weekly
  `.service`, and `scenario-benchmark.py` prints with `flush=True`.

## What changed (commit 9c58d304b3d on dispatch branch)

- `stacks/services/ada-scenario-runner/ada-scenario-smoke.container`:
  `TimeoutStartSec` 2700 → **7800** (~130min, covers observed range +
  margin); added `Environment=SCENARIO_BUDGET_S=7000` — inert until the
  ada-voice patch lands, then stops the run gracefully between
  scenarios ~800s before the unit cap.
- `stacks/services/ada-scenario-runner/README.md`: scheduling section
  updated — weekly `:55` slots can now be lapped by a long smoke run;
  the 30-min `:8199` wait queue absorbs it; hourly timer self-throttles
  (fires that find the lock held exit 0 immediately), so effective
  cadence ≈ run length instead of truncated hourly.
- `docs/kb/patches/ada-scenario-report-truncation-20261124.patch`: patch
  against ada-voice `scripts/scenario-report.py` (verified `git apply
  --check` clean on ada-voice HEAD efad065) implementing card option
  (c): `_prior_statuses()` reads latest per-scenario status from MDDB
  and runs **fail → flaky → never-reported → rest** (a-z fallback on
  MDDB hiccup), plus `--budget-s`/`SCENARIO_BUDGET_S` graceful stop.
  Module compiled, ordering unit-checked, `--dry-run` exercised.
- `docs/ssot/jobs/ada/2026-11-24-smoke-timeout-truncation.yml`: decision
  record — chose (d)+(c); rejected (a) parallelism (shared Ada session /
  vcast screens contaminate — documented 2026-09-30 incident; :8199 lock
  exists to serialize; parallel free-lane ws sessions would multiply
  429 risk) and deferred (b) tier split (needs ada-voice tier semantics;
  unnecessary once the cap fits).

## Not done / needs a human or follow-up

- **Not deployed** (dispatch scope). Activation on idc03: apply the
  patch in the ada-voice repo (tony-dell edit point per its AGENTS.md),
  push through `deploy-ada.sh`, then re-run
  `stacks/services/ada-scenario-runner/install.sh` on idc03 (or re-copy
  the smoke `.container` + `daemon-reload`) for the new TimeoutStartSec.
  The timeout bump alone fixes truncation; the patch adds ordering +
  budget on top.
- `ada-scenario-full.container` has the same shape (3600s vs ~157
  scenarios) but is manual/card-gated — noted as follow-up in the job
  doc.

## How to verify

After deploy: `journalctl --user -u ada-scenario-smoke` shows all 47
`== <name>: <status>` lines + final `N scenarios:` summary in a single
run with no kill; `ada-ha-scenario-reports` has a `report/*-<ts>` doc
per scenario per run; journal order shows prior fail/flaky scenarios
first once the patch is live.

lessons:
- Dispatch worktree boundary vs cross-repo fixes: when the code lives in
  another repo (ada-voice), ship a verified `git format-patch` under
  chaba `docs/kb/patches/` (precedent exists) + pre-arm env flags the
  old code ignores harmlessly.
- `scenario-report.py --dry-run` still executes scenarios (only skips
  MDDB writes) — it is not a no-run flag; a dry-run against a dead lane
  just fast-fails every scenario infra.
- Pre-commit SSOT hooks can rewrite unrelated generated files
  (ssot.dev-system.assessment.yml) into the working tree post-commit —
  leave them; they regenerate each commit.
