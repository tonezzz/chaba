# Dispatch outcome — embed-lane-banks-service-on-id (OPS-1498)

Card: `embed-lane-banks-incremental-copy-fix`
Date: 2026-11-27

## What was wrong

`embed-lane-banks.service` on idc02 is a oneshot daily timer that copied
~112k docs (`ada-ha-bank-devin-handoff` alone) through mddb-embed :11028.
Every run was SIGTERMed at `TimeoutStartSec` mid-copy (~50 docs/s, killed
at the wall). The earlier `--budget 2400` cap (card
embed-lane-banks-bounded-run) made runs exit 0 but each run still
re-scanned every collection from row 0 and re-diffed the whole target —
the backlog could never drain and the alert kept flapping.

## What changed

`scripts/embed/embed-lane.py` — `banks` is now truly incremental:

- Per-bank cursor persisted in `~/.local/share/embed-lane/banks-state.json`
  (`offset`, `pass`, `src_total`, `copied_total`, `fail_total`,
  `pass_failures`, `have_refresh_in`, `synced_at`, `bad_keys`,
  `scan_failures`, round-robin `next_idx`). Saved after every page
  checkpoint, so a SIGTERM/budget stop loses at most one page.
- Persisted target key-set `banks-have/<coll>.keys` (append-only,
  atomic rename) so resume never re-fetches the whole target; refreshed
  via full paged `/v1/search` every `--have-refresh` runs (default 24).
- `_docs_pages()` gained a `start=` offset so the cursor actually
  resumes mid-collection instead of re-scanning row 0 (the first draft
  bug — caught by mock test).
- Bounded slices: `--budget` wall-clock and `--max-docs`/`--limit`
  per-collection cap; exit 0 on budget/cap completion, 1 on real errors.
- Synced banks skip until `--rescan-hours` (6h) or have-refresh; a
  wrapped pass with failures clears `synced_at`.
- Failure handling: `/v1/add` retries once, then quarantines the key in
  `bad_keys` after `BAD_KEY_FAILS=2` (cap 500, `--force` clears);
  `fail && !copied` → rc=1; src-scan transport drops count
  `scan_failures` per collection and only fail the run after
  `SCAN_FAIL_ALERT=3` consecutive errors (single "Remote end closed"
  blips self-heal via cursor instead of flapping the alert).
- New flags: `--max-docs`, `--rescan-hours`, `--have-refresh`, `--force`.

`docs/ssot/infrastructure/ssot.jobs.yml` — embed-lane-banks moved to
`every: 1h`, `timeout: 15m`, exec `banks --budget 600` (10min wall <
15min TimeoutStartSec). ExecStart deliberately keeps only `--budget`
(already-deployed flag) so the rendered unit is safe before idc02's
checkout syncs the new script.

`systemd/generated/idc02/embed-lane-banks.{service,timer}` re-rendered
(TimeoutStartSec=900, OnUnitActiveSec=60min);
`tests/ops/test_render_jobs.py` MIGRATED pin updated.

`docs/ssot/jobs/mddb/2026-10-27-embedding-backfill-lane.yml` refresh
note updated. `tests/embed/test_embed_lane.py` +4 tests
(TestBanksCursor: bounded resume/converge, no-rescan/no-dup,
all-add-failures rc=1, transient-scan-error threshold).

## Deploy + live verification on idc02

scp'd the script to `~/CascadeProjects/chaba/scripts/embed/` (exec
checkout; autostash-safe until the branch merges) and the rendered
units to `~/.config/systemd/user/` + `daemon-reload`.

- Run 1 (timer-fired 12:27 +07, pre-threshold script): 3164 docs
  delivered in the 10min budget, cursors persisted, small banks synced;
  exit 1 on one transient devin-handoff scan drop — this is what
  motivated `SCAN_FAIL_ALERT`.
- Run 2 (12:42, current script): **Result=success** — resumed
  `ada-ha-bank-devin-handoff` at offset=35000 (cursor persisted),
  synced banks skipped, small deltas copied; 2167 docs delivered,
  offset → 37070.
- Run 3 (12:53): **Result=success** — round-robin on
  infrastructure-ssot, queue saturated so 33 docs; clean budget exit.
- Run 4 (13:03): **Result=success** — devin-handoff offset → 37278,
  +201 docs; clean budget exit.
- Final state: 3 consecutive `Result=success`; 22/24 collections
  `synced_at`-clean; devin-handoff cursor 37278/112386 advancing,
  `copied_total` 4582, `scan_failures` 0; timer next fire 14:03 +07.
- Note: embed queue sits pinned at ~3000 (pool drain-bound, dropped=0)
  so copy rate is throttled to drain rate — by design; the backlog
  drains over hours, not one run.

## How to verify

- `ssh idc02 'systemctl --user show embed-lane-banks.service -p Result'`
  → `success` on consecutive runs.
- `ssh idc02 'journalctl --user -u embed-lane-banks.service -n 50'` —
  per-bank `offset=N/src_total` advancing toward 112386 for
  ada-ha-bank-devin-handoff.
- `ssh idc02 'cat ~/.local/share/embed-lane/banks-state.json'` —
  per-collection cursors; `synced_at` set on clean passes.
- `python3 -m pytest tests/embed/test_embed_lane.py tests/ops/test_render_jobs.py`

## Notes / follow-ups

- The worktree branch `dispatch/20261127-113424-embed-lane-banks-service-on-id`
  holds the change (2 commits); not pushed per dispatch rules —
  idc02's `chaba-repo-sync.timer` picks it up after merge and the
  rendered units are already live.
- Until merge, idc02's checkout carries the script as an uncommitted
  modification — `git-safe-pull --autostash` preserves it; after merge
  the file becomes clean upstream content.
- `docs/ssot/ssot.dev-system.assessment.yml` has an unrelated local
  modification (automated assessment refresh) left uncommitted.
- timer-alert-idc02-embed-lane-banks auto-closes via timer-sentinel
  `_live_verify` once `Result=success` is observed.

lessons:
- MDDB `/v1/search` always returns contentMd and ignores `include_content`
  — there is no key-only bulk mode; a persisted have-set file is the only
  cheap resume/dedup mechanism.
- A cursor offset is bookkeeping until `_docs_pages` accepts `start=` —
  mock-test resume by asserting which offsets get re-requested.
- `systemctl --user start` on a oneshot blocks until completion; use it
  deliberately or `--no-block` + journal polling for long budget runs.
- Concurrency hazard: a manual `banks` run overlapping the timer run
  shares banks-state.json — harmless (upsert idempotent, cursor
  self-heals) but avoid overlapping runs when precision matters.
- Timer `OnUnitActiveSec` re-arms on daemon-reload relative to last
  activation — deploying a new hourly timer can fire almost immediately.
