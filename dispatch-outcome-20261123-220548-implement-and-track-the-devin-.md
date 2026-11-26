# Dispatch outcome — implement-and-track-devin-telegram-repor-fc0dc7 (attempt 2)

## What this run did

Attempt 1 (dispatch/20261123-211631, session cactus-circus) implemented the
full deliverable but the auto-checkpoint commit only captured
`ssot.jobs.yml` — the script, tests, runbook and rendered units were left
untracked and the unit exited 1 at close-out. This run recovered those
untracked files from the still-present worktree
`dispatch-wt-20261123-211631-implement-and-track-the-devin-`, ported them
into this worktree, re-verified everything, and committed.

## Deliverables (all on branch dispatch/20261123-220548-implement-and-track-the-devin-)

- `scripts/ops/devin-dispatch-tg-watch.py` — one-shot poller (nest-queue-watch /
  kanban-notify pattern). Pages MDDB `/v1/search` over
  `ada-ha-bank-devin-handoff` (`filterMeta kind=job|answer`, paginated —
  `/search` caps at 1000 unordered rows and the ledger is ~1.5k), diffs each
  doc's `sha1(key+status+contentMd)` signature against
  `~/.local/state/devin-dispatch-tg-watch.json`, and sends one
  `board_notify.send()` per new state: started / done / FAILED /
  needs input (awaiting-user) / answered. First tick primes silently;
  `DEVIN_TG_WATCH_CATCHUP_MIN=<n>` re-admits recent docs;
  `DEVIN_TG_WATCH_STATUSES` filters; kill switch
  `~/.config/devin-dispatch-tg-watch.off` or `DEVIN_DISPATCH_TG_WATCH=off`;
  max 5 sends/tick; failed sends retain their slot for next-tick retry.
- `docs/ssot/infrastructure/ssot.jobs.yml` — job `devin-dispatch-tg-watch`
  on idc03, every 5m, `BOARD_NOTIFY_CHANNEL=tg`,
  `BOARD_NOTIFY_TG_CHAT_ID=-5410424865` (ada-ha group via the loopback
  relay /send on :8911).
- `systemd/generated/idc03/devin-dispatch-tg-watch.{service,timer}` —
  rendered units.
- `tests/ops/test_devin_dispatch_tg_watch.py` — 9 unittest cases.
- `docs/ssot/jobs/board/2026-11-23-devin-dispatch-tg-reporting.yml` —
  runbook: channel decision, ledger contract, verification, deploy steps,
  followups.

Also re-rendered pre-existing manifest drift so the repo consistency test
is green again (unrelated to this card but required for a clean suite):
`idc02/log-shipper{,-severe}.service` (timeout 600→1800 per jobs.yml) and
new units for `idc03/ada-morning-brief` + `idc03/mcp-fleet-report`.

## Verification (done-condition: successful test run, expected output, no errors)

- `python3 -m pytest tests/ops/test_devin_dispatch_tg_watch.py` — **9/9 pass**.
- `python3 -m pytest tests/ops tests/test_render_jobs_catalog.py` — **110/110 pass**
  (the manifest drift test was red on master before this change).
- `python3 scripts/render-jobs.py --check` — OK 118 jobs, 8 hosts.
- Live smoke on tony-dell against the real idc03 MDDB ledger with
  `BOARD_NOTIFY_CHANNEL=file` sink: first tick primed, `CATCHUP_MIN=2880`
  emitted real `[devin] <job> started|done|FAILED` events (117 backlog
  events drained at the designed 5/tick cap), then went fully silent —
  dedupe and steady-state confirmed, rc=0 throughout.

## Deploy (needs merge + explicit approval — NOT done here)

On idc03 after merge: `python3 scripts/render-jobs.py --host idc03
--ids devin-dispatch-tg-watch --install`. First tick primes silently —
set `DEVIN_TG_WATCH_CATCHUP_MIN` in the unit env first if the install
tick should prove itself with recent events. Off switch:
`touch ~/.config/devin-dispatch-tg-watch.off` on idc03.

## Notes / followups

- The runbook records a ledger-health observation: ~76% of recent job
  docs still say `running` (terminal writes missing on many hosts) —
  the TG lane reports whatever the ledger says; worth a separate look.
- Prior unit failures were close-out/infra exits, not work defects —
  same pattern as the ansible-vs-legacy-fleet-benchmark KNOWN_GOOD note.

lessons:
- Dispatch auto-checkpoint commits only TRACKED files — new scripts/tests
  left untracked are lost from git even though the session "completed".
  Always `git add` deliverables explicitly before ending a dispatch.
- A failed dispatch unit (exit=1 at close-out) does not mean the work
  failed — check the old worktree for untracked deliverables before
  re-implementing from scratch.
- `tests/ops/test_render_jobs.py::test_generated_tree_matches_manifest`
  goes red whenever ssot.jobs.yml changes land without re-rendered
  `systemd/generated/` units — run render-jobs for touched jobs before
  committing job changes.
