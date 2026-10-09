# Dispatch outcome — fix-idc02-audit-suite

## Result: done — audit suite exits 0 on idc02 (default and --full)

### What the Oct-04 findings actually were

- **security-audit docker call (line ~263)** — already fixed in `35c0cb1a`
  (same day, after the run): `check_database_security` now picks
  `docker|podman`. The remaining docker-only block was
  `check_docker_security` — silently skipped on idc02. **This session**
  made it runtime-aware (`docker → podman → podman-remote`, skip-with-log
  when absent). Under rootless podman it flags `--privileged` containers
  (none fleet-wide today) instead of image-default `User:""` — namespaced
  root isn't host-root; the empty-User medium check is kept for rootful
  runtimes. `/var/run/docker.sock` check stays docker-specific.
- **caddy "format failed"** — was a missing `caddy` binary (spawnSync
  status=null → empty error), not a fmt error. `35c0cb1a` added the
  podman `caddy:2` fallback; verified passing on idc02 today. Also
  committed the canonical `caddy fmt` output for `stacks/web/Caddyfile`
  (gesture-live merge left double blank lines + misindented header
  blocks) so the audit's `fmt --overwrite` is idempotent.
- **standardization "duplicate audit name: cms-pages"** — already fixed
  in `35c0cb1a` (renamed to `cms-pages-live`); verified.
- **cms-pages dead mddb IP** — warn-severity, doesn't gate; owned by
  card `sweep-stale-mddb-endpoint`. Noted in the job log.

### New findings surfaced while re-running (fixed)

- `standardization`: `camwall-smoke.yml` references `scripts/cam-wall`
  but had no quality-registry entry → added `ci.camwall-smoke` to
  `ssot.quality.yml`.
- `doc-links` (error-severity, **still failing on the live checkout**):
  `7cc7f18f` retired `stacks/tony-dell/rview-*` but the migration runbook
  + `ssot.runbooks.yml` registry still listed them → dropped dead
  `related:` paths (doc kept as historical).

### Verification

- `node scripts/audits/run.mjs` in the worktree: **exit 0**, 7 warnings
  (mddb, cms-pages, code-quality, dev-system, http-health, staleness,
  memory-banks — none gate).
- `node scripts/audits/run.mjs --full`: **exit 0**, 14/22 pass, 8
  warnings (adds security-posture), 0 failures. `security-audit` passes
  standalone and under the runner with the new podman path.
- `ssot-validate-all`: 1794 files, 0 errors.
- Caveat: I did **not** run `systemctl --user start chaba-audit.service`
  — the unit runs `~/CascadeProjects/chaba` (live checkout), which still
  fails `doc-links` until this branch merges. After merge, the next
  scheduled run (weekly Sun 02:00 / monthly Nov 1) goes green and clears
  the `failed` marks automatically.

### ssot.audit.hosts.yml

No `known_failed` entries for `chaba-audit.service`/`chaba-audit-full.service`
existed (idc02's list was already `[]`) — nothing to remove. Added both
audit timers to idc02 `expected_services` so `audit-hosts.py` verifies
them going forward.

### Files changed (commit `a644f413` on `dispatch/20261009-164359-from-reports-audits-summary-js`)

- `scripts/security-audit.sh` — container-runtime detection
- `stacks/web/Caddyfile` — `caddy fmt` normalization
- `docs/ssot/infrastructure/ssot.quality.yml` — `ci.camwall-smoke`
- `docs/ssot/ssot.runbooks.yml`, `docs/runbooks/tony-dell-rview-gemini-migration.md` — dead `related:` cleanup
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — idc02 audit timers
- `docs/ssot/jobs/infrastructure/2026-10-09-fix-idc02-audit-suite.yml` — job log
