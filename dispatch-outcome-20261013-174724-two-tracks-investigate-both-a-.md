# Dispatch outcome — fix-mddb-stats-timeout-overnight (attempt 3)

## Track A — why /metrics + /v1/stats "hang" on idc03 :11023

Not a service outage — endpoint-level starvation on a big DB:

- The 2026-10-13 02:00 overnight health_snapshot ran while mddb was **up**:
  `/v1/vector-stats` answered in 540ms in the same window, `/health` is fine.
  `mddb-stats` timed out at 60s (+2x retry) and `mddb-metrics` at 5s (+10s retry).
- `/v1/stats` is an **O(full-DB) walk**: ~1.6M keys + per-collection checksums
  over an **8.2GB** `mddb.db` (+ 99MB binlog). Warm it takes ~0.9–1s, but the
  first cold-cache walk of the night exceeds the 60s declared timeout — and
  while it runs it starves the sibling probes (`/metrics` >5s+10s,
  vector-stats degraded to ~540ms).
- Recurring amplifier found in the logs: `mddb-backup.timer` fires **02:30
  nightly** → `~/mddb-backup.sh` → native `/v1/backup` → **integrity check
  reads all 8.3GB over ~13 min** (02:31:01→02:44:00, cpu=126s). It doesn't
  overlap the 02:00 health step today, but any probe inside that window hits
  the same starvation — explains other sporadic slow nights.
- `/v1/vector-stats` ~425–540ms is just its baseline (index metadata), not a
  hang symptom.
- Root fix is already carded: **mddb-stats-o1-counts** (O(1) counters in the
  mddb fork). This card tracks the audit/policy side.

## Track B — audit no longer fails the rollup on slow stats endpoints

`scripts/audits/http-health-audit.mjs` now honors a per-service
`severity: warning` field in the health SSOTs:

- failures (unreachable/timeout-after-2x-retry/wrong status/cert <7d) on a
  warning service are recorded as warns tagged `(non-fatal)` — reported but
  exit code stays 0. Default remains error; opt-in only.
- every check entry now carries a `severity` field; a `warning` mark on any
  declaration of the same URL wins the dedupe merge.

Applied `severity: warning` (+ rationale notes) to the three mddb
**diagnostic** endpoints in `ssot.health.home.datastore.yml` and
`ssot.health.mobile.yml`: `mddb-stats`, `mddb-metrics`, `mddb-vector-stats`.
`mddb-api` (`/health`) stays fatal — a genuinely dead mddb still fails the
audit, so no coverage is lost.

## Files changed

- `scripts/audits/http-health-audit.mjs`
- `docs/ssot/infrastructure/ssot.health.home.datastore.yml`
- `docs/ssot/infrastructure/ssot.health.mobile.yml`
- `docs/ssot/jobs/infrastructure/2026-10-13-mddb-stats-endpoint-starvation.yml` (trail)

## How to verify

- `node scripts/audits/http-health-audit.mjs` → exit 0; live run produced
  ok=true, 86 checks, 0 issues, mddb stats entries carry `severity:"warning"`.
- Fixture test done: dead endpoint with `severity: warning` → warn
  `(non-fatal)`, exit 0; same endpoint at default severity → issue, exit 1.
- `node scripts/ssot-validate-all.mjs` → both edited health files valid
  (2 unrelated pre-existing job-file errors remain).
- Tonight: health_snapshot should stay rc=0 even if mddb stats time out.

## Prior-attempt note

Attempt on tony-omen (checkpoint 513db4b3) reached the same conclusions but
its merge was held by an unrelated ada test-gate failure and the worktree was
left dirty; this run re-implemented the audit fix cleanly on chaba.

lessons:
- dispatch worktrees have no node_modules — `ln -s <live-checkout>/node_modules node_modules` unblocks js-yaml scripts, but the symlink is NOT covered by the `node_modules/` gitignore pattern (dir-only) — remove it before committing.
- plain unquoted YAML `note:` scalars cannot contain `: ` — folded note lines like "severity warning (2026-10-13): ..." fail ssot-validate; use `—` instead.
- ORCHESTRATION.json steps lack timestamps; reconstruct probe windows from run_id + per-step duration_ms before blaming a concurrent job (the 02:30 backup integrity check did NOT overlap the 02:00 failure).
- board-api /cards comms text truncates ~500 chars — keep final comms short or split them.
