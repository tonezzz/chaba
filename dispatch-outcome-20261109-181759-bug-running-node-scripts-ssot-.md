# Dispatch outcome: ssot-optimize-baseline-refresh-crash

## Root cause

`scripts/ssot-optimize.mjs` ran `ssot-validate-all.mjs` via `execSync`.
`execSync` throws whenever the child exits non-zero — and the validator
exits 1 by design whenever ANY file has validation errors
(`process.exitCode = totalErrors > 0 ? 1 : 0` in ssot-validate-all.mjs).
So whenever the tree had even one pre-existing validation error, the
"full run" the pre-commit hook prescribes crashed with an uncaught
error whose object dump contained the entire ~340KB validator stdout.
(It looked like a maxBuffer/E2BIG overflow, but 340KB is well under the
1MB default — the dump is just the thrown error's captured stdout.)

## Fix

`scripts/ssot-optimize.mjs` `main()`:

- `execSync` → `spawnSync(process.execPath, ["scripts/ssot-validate-all.mjs", ...args])`,
  reading `result.stdout` regardless of `result.status`. Non-zero exit
  is now a normal path, not an exception.
- `maxBuffer: 64 * 1024 * 1024` as headroom over the current ~340KB report.
- Warns (instead of silently writing an empty report) if the validator
  produced no stdout at all.
- `args` passed as an array instead of string interpolation (also safer
  for args containing spaces).

## Verification

`node scripts/ssot-optimize.mjs` in this worktree (which has 7
pre-existing validation errors and 126 warnings — the exact crash
condition): exits 0, writes all three reports. WARNINGS.json parsed
102 bloat + 23 data-isolation + 8 other warnings; METRICS/SUGGESTIONS
consistent. `reports/SSOT_OPTIMIZATION_WARNINGS.json` and the
`ssot.dev-system.assessment.yml` metrics refresh (a normal side-effect
of the run's dev-system check) are included in the commit.

Commit `2946929d3` on `dispatch/20261109-181759-bug-running-node-scripts-ssot-`
(pre-commit hooks passed).

## Note on the triggering context

The merge-gate misclassification (24 pre-existing bloat warnings flagged
as "new debt") is a separate issue in whatever staged-diff gate reported
it — this fix only removes the crash in the remediation path.
