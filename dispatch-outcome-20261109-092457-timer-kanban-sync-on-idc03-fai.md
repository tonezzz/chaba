# Dispatch outcome — timer-kanban-sync on idc03 (2026-11-09)

## Task
Investigate `kanban-sync.service` on idc03 failing with result=exit-code
(card `timer-alert-idc03-kanban-sync`, first alert 11-08 12:00).

## Findings (from `journalctl --user -u kanban-sync.service` on idc03)

29 failed runs since 11-08 12:00, two independent causes:

1. **git-fetch ref-lock race (5 failures)** — 11-08 12:00/17:00/19:00 and
   11-09 03:00/07:00. `git fetch` aborted with
   `cannot lock ref 'refs/remotes/origin/chaba.h3' (once also origin/master):
   is at X but expected Y`. The kanban-sync worktree shares the
   `chaba-tony-dell` gitdir with `kanban-commit.timer` (15-min cadence,
   randomized delay) — when both fetch while dispatches land `chaba.h3`
   branch updates, the loser exits nonzero and the script `exit 1`s.

2. **mddb-cms embed-queue outage (~24 failures)** — overnight 00:19–06:49 on
   11-09, `mddb add dev-kanban/{en,th}` got "Remote end closed connection" /
   timeouts → `kanban-cms publish=FAIL` → script exit 1 (it's the last
   command). Cause: mddb-cms embed queue pinned at 4000 with >2300 dropped
   vector jobs — "all same-space providers down (OR circuit-open + Gemini
   failed)" while mddb-embed was mid-9h40m vector-index load after a 11-08
   ~13:30 restart. Queue drained ~07:15; every run since (07:19→09:21) is
   `publish=ok`, exit 0. mddb-cms `/v1/health` = healthy at 09:26.

## Changes

- `scripts/ada/kanban-sync.sh` — `git fetch origin` now retries 3x with 10s
  backoff before failing (OPS-0834 retry-safe standard, same pattern used
  for the chaba.h3 push races on tony-dell). `bash -n` clean.
- New job record: `docs/ssot/jobs/kanban/2026-11-09-kanban-sync-idc03-fetch-race.yml`.
- Posted RCA to card `timer-alert-idc03-kanban-sync` via board-api.

Not changed: `kanban-cms` publish stays fatal — a real mddb degradation the
sentinel should keep surfacing.

## Verify

- `ssh idc03 'journalctl --user -u kanban-sync.service --since today'` —
  next ticks should show no `fetch failed` exits; transient races now log
  nothing fatal (retry inside the loop).
- `ssh idc03 'systemctl --user status kanban-sync.service'` — last run
  09:21 exit 0.
- `curl http://100.102.134.91:11027/v1/health` → `status: healthy`.

## Deferred (noted in job record / card comms)

- ~2300 CMS docs lost vectors during the embed outage — reindex if semantic
  search misses them.
- mddb-embed probe shows "queue stats unavailable: timed out" at 09:00/09:15
  (probe itself reports up, 3 hits) — embed bank still slow on stats.
- runner-fleet-health also flagged `idc03/no-push-creds` and devin-dispatch
  sha drift — separate existing cards.
