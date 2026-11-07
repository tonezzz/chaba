# Dispatch outcome — repair-wp-nest-job-cpt-drift (re-dispatch 2026-10-26 19:24)

## Status: DEPLOYED + VERIFIED — repair complete

This was a verification re-dispatch of the card: the prior session
(20261026-185925) diagnosed the drift, staged `chaba-boards-0.9.0.zip`,
obtained Tony's `proceed` gate answer, and deployed at ~19:07. This
session confirmed the repair holds live and closed the evidence gaps
(authed plugin version + meta read-back).

## Root cause (from prior session, confirmed)

Not a revert — a never-executed deploy. Live plugin was ~v0.7.x while
repo `integrations/wp-boards/chaba-boards.php` was v0.9.0; the v0.8.0
(activity) and v0.9.0 (nest_job) deploys both stalled at the Tony gate.
KNB-0659's "all CPTs registered" was true at v0.3.3 and predates both
CPTs.

## Live evidence gathered this session

- `GET /wp/v2/plugins` (authed, idc03 `wp-boards.env`):
  `{"plugin":"chaba-boards/chaba-boards","version":"0.9.0","status":"active"}`
  — live and repo now match.
- `GET /wp/v2/types`: 31 types; `nest_job` and `activity` present.
- Anonymous `GET /wp/v2/nest_job` and `/wp/v2/activity` → **200 `[]`**
  — route live, zero private posts leaked.
- `bash scripts/wp-boards/verify-nest-job.sh repair-verify` → **PASS**:
  - parent create: post 2605 (`repair-verify-202610261925-parent`)
  - child create: post 2606 via `parent=<slug>` → `parent: 2605`
  - parent update: `action=updated`, meta merge accepted
- Authenticated meta read-back (same creds board-api uses):
  - post 2605 meta: `status=done`, `result_ref=probe://verify-ok`,
    `comms` JSON log holds both appended entries — write + meta-merge +
    read round-trip complete
  - post 2606 meta: `kind=sub`, `pack=probe-pack`,
    `runner=verify-script`, `parent=2605`
- Both new health probes answer live: `wp-nest-job-cpt` → 200,
  `wp-activity-cpt` → 200 (404 = plugin regression → mcp-health →
  focus-inbox, before any DevNest job needs /job).

## Changes committed on dispatch/20261026-192455-investigate-and-repair-the-liv

- `docs/ssot/apps/ssot.wp-boards.yml` — v0.8.0/v0.9.0 flipped to
  DEPLOYED 2026-10-26; drift note rewritten as FOUND+REPAIRED with the
  verification summary.
- `docs/ssot/jobs/infrastructure/2026-10-26-nest-job-cpt-drift-repair.yml`
  — status `deployed-verified`; `post_deploy_verified` evidence block
  added; followup updated.

No push, no live-config changes this session (deploy already done by
the prior session under the gate). No deletion or public publishing —
all probe posts are `status: private`.

## Open follow-ups

- `activity-posts.timer` on idc03 is `disabled`/`inactive` — the
  activity CPT now exists so its POSTs would succeed, but enabling the
  writer is a separate Tony decision (raised in card comms).
- board-api has no `/job` read op — meta read-back needs WP creds on
  idc03 (already in trail-doc followups).

## Verify this report

- `curl -s 'https://boards.surf-thailand.com/wp/index.php?rest_route=/wp/v2/nest_job&per_page=1'` → 200 `[]`
- `bash scripts/wp-boards/verify-nest-job.sh` → RESULT: PASS
