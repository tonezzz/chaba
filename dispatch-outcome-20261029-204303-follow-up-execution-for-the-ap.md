# Dispatch outcome — OPS-0790 dispatcher→systemd migration (code phase)

## What changed

All eight remaining `dispatch: dispatcher` entries in
`docs/ssot/infrastructure/ssot.jobs.yml` were converted to
`dispatch: systemd` with every declared field preserved (host, `every:`
cadence → `OnBootSec=1min`+`OnUnitActiveSec`, `timeout:` →
`TimeoutStartSec`, `cwd:` → `WorkingDirectory`, `exec:` → `ExecStart`,
`env_file:` → `EnvironmentFile`, `condition_path:` →
`ConditionPathExists`):

- embed-lane-news, embed-lane-lessons (idc03), embed-lane-banks (idc02)
- yomi-update-active (idc03)
- mcp-debug-h3-sync, tony-dell-health-snapshot, network-scan-tony,
  lesson-drift-check (tony_dell)

`network-scan-tony`'s `critical: false` was dropped (the flag is
dispatcher-only); the isolation it encoded is structural under per-unit
timers, and failure alerting moves to timer-sentinel's `timer-alert-*`
cards.

`scripts/render-jobs.py` gained the dispatcher's podman stale-`--name`
preclean as `ExecStartPre=-/usr/bin/podman rm -f <name>` for any exec
carrying `podman … --name` (OPS-0531 wedge parity; also fixes the same
latent gap on the already-migrated `yomi-update-all`).

`systemd/generated/` was re-rendered and reconciled: 16 new units for
the migrated jobs, 70 stale units deleted (chaba-jobs.* on idc03/tony_dell
plus host-move cruft that predates this change — con01 jobs still had
copies under idc02/, ~46 retired units under tony_dell/, orphaned
ada-lesson-miner), `yomi-update-all.service` modified (+1 preclean line).

`docs/kb/timer-expectations.md` updated for the new model.
`docs/reports/dispatcher-systemd-migration-2026-10-29.md` has the full
per-job mapping table and nine documented exceptions/deltas (E1–E9):
notably `env_file`/`condition_path` were *dead fields* under
job-dispatcher (now actually effective), backoff and the timeline.jsonl
results record are not replicated, audit-census entries for the three
not-yet-declared timers are deferred to rollout to avoid false
timer-alert cards.

## Tests

`tests/ops/test_render_jobs.py` — 16 new tests: manifest pins (zero
dispatcher jobs remain), per-field render preservation, podman preclean
matrix, contract guards, and a generated-tree↔manifest parity check that
prevents the stale-units drift from recurring.

## Verified

```
python3 -m unittest tests.ops.test_render_jobs tests.ops.test_job_dispatcher  # 28 OK
python3 scripts/render-jobs.py --check   # OK 87 jobs, 8 hosts
node scripts/ssot-validate-all.mjs       # 3278 files, 0 errors
```

## NOT done (by design — separate deploy-lock rollout)

- No timers installed/enabled; live `chaba-jobs.timer` untouched.
- `scripts/job-dispatcher.py` and the `config.dispatcher*` block remain
  (contract still renders for future `dispatch: dispatcher` jobs; removal
  is the cleanup step after live rollout verifies).
- Audit-census additions for embed-lane-*/lesson-drift-check timers —
  deferred to rollout (E9).
