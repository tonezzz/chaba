# Dispatch outcome — repair-wp-nest-job-cpt-drift (2026-10-26)

## Status: INVESTIGATED + REPAIR STAGED — awaiting Tony deploy gate

## Findings (live-verified)

- `GET https://boards.surf-thailand.com/wp/index.php?rest_route=/wp/v2/types`
  lists 21 types — **`nest_job` and `activity` are absent**; all older
  chaba-boards CPTs (asset…score…xlate) present → live plugin is ~v0.7.x.
- `GET /wp/v2/nest_job&per_page=1` → **404 `rest_no_route`** (same for
  `activity`); `/wp/v2/lesson`, `/wp/v2/score` → 200 — discriminates
  registered-vs-missing cleanly even anonymously.
- board-api `POST /job` → 502 surfacing `wp /wp/v2/nest_job -> 404` —
  reproduces the reported symptom.
- Root cause is **a never-executed deploy, not a revert**: repo
  `integrations/wp-boards/chaba-boards.php` = v0.9.0 (unchanged since
  cdecf8cca, 2026-10-23); both v0.8.0 (activity) and v0.9.0 (nest_job)
  trail docs recorded "needs Tony approval — until it lands POSTs 404".
  KNB-0659's "all CPTs registered" was true at v0.3.3 (2026-10-14) and
  predates both CPTs.
- Collateral check: `activity-posts.timer` on idc03 is disabled/inactive,
  so the missing CPT caused no silent write failures.
- Contract side is intact: `python3 -m unittest
  tests.board.test_board_api_mutations` → 17/17 OK.

## Repair prepared (not yet applied)

- `integrations/wp-boards/dist/chaba-boards-0.9.0.zip` built
  (`chaba-boards/{chaba-boards.php,usage-pull-cron.php}`,
  md5 97bc092147e1d559f071c55e71e29d77); `php -l` clean on tony-omen.
- Zip staged at `tony-omen:/tmp/chaba-boards-0.9.0.zip`;
  `deploy-plugin-zip.sh` + wp-admin creds confirmed present on omen.
- Deploy command (after gate):
  `ssh tony-omen 'bash ~/CascadeProjects/chaba/scripts/wp-boards/deploy-plugin-zip.sh /tmp/chaba-boards-0.9.0.zip'`
- Board request `live-chaba-boards-plugin-is-v0-7-x-wp-v2-0dc69c` raised;
  ★ = "proceed — run deploy-plugin-zip.sh from omen now".

## Changes committed on this dispatch branch

- `integrations/wp-boards/dist/chaba-boards-0.9.0.zip` (new)
- `scripts/wp-boards/verify-nest-job.sh` (new) — creds-free post-deploy
  verify: types list, anonymous-privacy check, /job parent create →
  child create via `parent=<slug>` → parent update w/ comms+meta merge.
- `docs/ssot/infrastructure/ssot.health.home.web.yml` — new http probes
  `wp-nest-job-cpt` + `wp-activity-cpt` (200 vs 404 regression detection
  via mcp-health → focus-inbox).
- `docs/ssot/apps/ssot.wp-boards.yml` — drift finding recorded on the
  v0.9.0 note.
- `docs/ssot/jobs/infrastructure/2026-10-26-nest-job-cpt-drift-repair.yml` — trail doc.

## Remaining (post-gate)

1. Run the deploy command above.
2. `bash scripts/wp-boards/verify-nest-job.sh` — expect: both CPTs in
   /wp/v2/types, anon GET 200 `[]`, /job create/update ok+post_id.
3. Flip ssot.wp-boards.yml v0.8.0/v0.9.0 → DEPLOYED + date.
4. Enable/confirm `activity-posts.timer` on idc03 once the CPT exists.

## Verify this report

- `curl -s 'https://boards.surf-thailand.com/wp/index.php?rest_route=/wp/v2/nest_job&per_page=1'`
  — 404 before fix, 200 `[]` after.
