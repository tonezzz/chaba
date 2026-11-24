# Dispatch outcome — lesson-audit-scheduled (AUD-0831)

Session: 20261124-160340-wire-lesson-polish-pack-to-a-s
Branch: dispatch/20261124-160340-wire-lesson-polish-pack-to-a-s
Commits: d62610a25e (compaction checkpoint, incl. first-pass edits),
c71906cd0f (final: bulk read + queue + docs)

## What changed

The lesson-polish audit is now a self-perpetuating loop. Each daily
`chaba-lessons-audit` run (07:40 idc03, already scheduled) audits,
reports, and queues the Fable polish pass when policy flags exist.

- **scripts/board/board-api.py** — `/lesson op:list` on the wiki source
  honors `content=1`/`full=1`: rows gain `content`+`meta` from the
  namespace scan the door already performs (zero extra upstream calls).
  Selftest asserts content absent by default, present with the flag.
- **scripts/lessons-audit.py** — rewritten (83 → ~450 lines):
  - Fetches ALL lesson bodies in ONE `op:list{content:1}` call;
    parallel `op:get` (8 workers) remains only as fallback for
    wp/mddb sources or a pre-change door.
  - Writes `docs/reports/lesson-audit/{<date>,latest}.json` (was
    untracked `out/`); `kanban-commit.sh` sweeps the new dir.
  - Posts a one-line comms summary to card `lesson-audit-scheduled`.
  - When R1/R3/R4 flags exist: re-arms standing card
    `lesson-polish-run` via `POST /card {queue:true,
    on_exists:"queue", action:{type:dispatch, repo:chaba,
    executor:devin}}` + posts the flagged list as card comms.
    Flag-signature (sha1 of slug|flag pairs) + `queued_at` state dedups
    re-arms: changed signature → immediate, unchanged → max 1 per 20h
    (`LESSON_POLISH_MIN_INTERVAL_H`). `>20%` get-errors skips queueing;
    `LESSON_POLISH_QUEUE=0` = report-only. R2/R5 never queue spend.
  - `audit_one` signature/behavior unchanged (education-report imports
    it); `--dry-run` prints intended writes without posting.
- **docs/ssot/infrastructure/ssot.jobs.yml** — job note updated.
- **docs/ssot/jobs/education/2026-11-24-lesson-audit-schedule.yml** —
  runbook: loop, dedup/bounds, files, verify, known gaps.

## Root cause found while verifying

The recurring `chaba-lessons-audit` 10m timeouts were NOT the old WP
serial fetch — the lesson store has cut over to the wiki `Education:`
namespace (`WIKI_EDUCATION_WRITE=wiki`), where EVERY `op:get` rescans
all ~221 pages (~13s each → ~48min serial). `op:list` alone took 13s
warm / >60s cold through the tailnet door. The `content=1` bulk read
eliminates the per-slug scan entirely: one call, all bodies.

## Verified

- `python3 scripts/board/board-api.py --selftest` → ok (incl. new
  content=1 assertions).
- `pytest tests/test_education_report.py` → 13 pass.
- Mocked end-to-end dry-run: list→flags→`new-flags` decision→queue
  payload correct, zero posts in dry-run.
- Live door probes: `/health` 200/51ms, `/comment` 200/67ms,
  `/lesson op:list` (default→wiki) 200/13.2s, 221 lessons.
- `/card` payload validated against `do_create`: id/executor/repo/
  on_exists/queue all whitelisted (`chaba` repo, `devin` executor).

## Deploy note / caveat

`content=1` must reach idc03's board-api (kanban-commit pulls +
restarts `chaba-board-api.service` on merge). Until then the audit's
`content=1` is ignored → rows lack `content` → falls back to parallel
gets — correct but on wiki source still >10m, so the job may time out
those days without queueing wrong work. First fast run is the first
07:40 after merge+restart.

## How to verify live

- `journalctl --user -u chaba-lessons-audit.service` on idc03 →
  "polish new-flags -> lesson-polish-run" (or throttled/clean).
- Board: card `lesson-polish-run` appears queued; `lesson-audit-scheduled`
  gets the daily comms line; `docs/reports/lesson-audit/latest.json`
  exists in the served checkout.
- Manual: `python3 scripts/lessons-audit.py --dry-run` on idc03.

lessons:
- wiki lesson op:get rescans the whole Education: namespace per call — any bulk read must use op:list (now content=1), never per-slug gets.
- default /lesson source follows WIKI_EDUCATION_WRITE — the store already cut over to wiki; WP is a frozen archive, don't audit it.
- dispatch compaction commits sweep the working tree — check git log before assuming edits are uncommitted.
- board-api 503 'lock saturated' is normal under kanban-commit races; one retry after ~12s is enough.
