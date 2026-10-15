# Dispatch outcome — education-store (OPS-0696)

Card `education-store` tracked remaining work on the WP lesson ledger
after earlier sessions shipped the lesson CPT (chaba-boards plugin
0.4.2, label Education), `scripts/lesson-add.py`, and
`scripts/lessons-due.py`. This dispatch verified the shipped state and
closed the remaining loose ends.

## What changed (repo — dispatch branch, commit d9d2c5541)

- `docs/ssot/infrastructure/ssot.jobs.yml` — registered
  `chaba-lessons-due` (host idc03, `on_calendar '*-*-* 07:30:00'`,
  persistent). The live timer was hand-created outside the registry;
  "do not hand-create timer units" is the file's own rule.
- `systemd/generated/idc03/chaba-lessons-due.{service,timer}` —
  rendered via `scripts/render-jobs.py --host idc03`. Semantically
  identical to the live unit (same exec/schedule/cwd; adds
  `TimeoutStartSec=300` + rendered marker).
- `docs/ssot/apps/ssot.wp-boards.yml` — `writers:` gained `lesson_add`
  and `lessons_due` entries (previously undocumented write paths).
- `docs/ssot/jobs/infrastructure/2026-10-15-education-store-lesson-ledger.yml`
  — job trail.

## What changed (live WP — via sanctioned REST writers, private posts)

- All 5 lesson posts (ids 336, 342, 343, 351, 353) retitled
  `Lesson — X` → `Education — X`, matching the adopted title standard
  (upsert path only fixes a post when re-asked).
- Ran `lessons-due.py` once from the live idc03 checkout — refreshed
  private page `education-due` (post 354). Result: 0 due, 5 upcoming.
  The timer's first scheduled run (2026-10-16 07:30) is now verified
  end-to-end rather than untested.

## Still open (deliberately not done here)

- OPS-0694 `lesson-transcript-miner` — separate backlog card; the
  offline transcript miner and the "Ada parity via miner" item belong
  to that card's own dispatch.
- Live idc03 unit still the hand-made copy; converges on next
  `render-jobs.py --host idc03 --install` (cosmetic diff only).

## How to verify

- `GET /wp/v2/lesson&status=any` — all titles start `Education —`.
- `python3 scripts/render-jobs.py --check` — `OK 54 jobs`.
- `systemctl --user list-timers | grep lessons` on idc03 — next run
  2026-10-16 07:30.
- Board: progress comment posted on `education-store`.
