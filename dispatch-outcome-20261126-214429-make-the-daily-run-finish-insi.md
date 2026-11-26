# dispatch outcome — embed-lane-banks-bounded-run (attempt 2)

## What changed

Commit `43d19819130` on `dispatch/20261126-214429-make-the-daily-run-finish-insi`:

- `scripts/embed/embed-lane.py` — `banks` subcommand gains `--budget <seconds>`,
  a run-wide wall-clock cap (`time.monotonic()` from cmd start). Checked:
  - before each collection,
  - before each `/v1/add` doc copy,
  - inside the `depth >= queue-hi` saturated-queue wait (previously an
    unbounded `sleep(30)` loop — the real timeout killer when the embed
    queue stays pinned at 3000).
  On exhaustion the run prints a clear "stopping run cleanly" line, finishes
  the per-collection summary, and exits 0. `--limit`, `--queue-hi 3000`,
  `--force`, and the `dropped` reporting are unchanged.
- `docs/ssot/infrastructure/ssot.jobs.yml` — job `embed-lane-banks` exec is now
  `... embed-lane.py banks --budget 2400` (40 min wall-clock inside the
  existing `timeout: 45m` → `TimeoutStartSec=2700`; 5 min margin covers
  collection fetch + final queue stats). Note updated with rationale.
- `docs/ssot/jobs/mddb/2026-10-27-embedding-backfill-lane.yml` — `embed-lane-banks`
  `refresh:` now documents the rendered `--budget 2400` cap and why.
- `systemd/generated/idc02/embed-lane-banks.service` — re-rendered via
  `scripts/render-jobs.py` (NOT hand-edited): ExecStart now carries
  `--budget 2400`; `TimeoutStartSec=2700` unchanged.

### Collateral generated-tree sweep (required by tests/ops/test_render_jobs.py::GeneratedTree)

Re-render drifted from the committed tree in three places, all legitimate
manifest-vs-tree drift, now synced:

- `systemd/generated/con01/cline-{board-mirror,intake}.{service,timer}` —
  DELETED. Cline was fully retired 2026-11-26
  (`docs/ssot/jobs/infrastructure/2026-11-26-cline-full-retirement.yml`);
  units are no longer in the manifest.
- `systemd/generated/idc03/wp-comment-sync.{service,timer}` — description
  string updated to match current manifest name.
- `systemd/generated/tony_dell/ansible-runner-tool-guard.{service,timer}` —
  NEW, job exists in manifest (line ~2182) but units were never rendered.

## Verification done here (con01 worktree)

- `python3 -m pytest tests/ops/test_render_jobs.py` — 27/27 pass, including
  `GeneratedTree` (tree == render(manifest) for all hosts).
- `python3 scripts/render-jobs.py --check` — OK, 134 jobs / 8 hosts.
- `py_compile` + `banks --help` — `--budget` wired.
- Functional stub test of `cmd_banks`: with `_docs`/`_post`/`_queue_depth`
  faked, `budget=0` copied all 499 todo docs; `budget=1` stopped at 23/499
  mid-collection, printed the budget-exhausted line, and the summary showed
  `23 docs delivered ... run budget exhausted — remaining docs resume next
  run`. Exit path is clean (no exception, returns normally → exit 0).

## NOT verified here — needs post-merge on idc02

The card's live verify ("one manual oneshot exits 0/SUCCESS with a nonzero
copy count and no timeout in journalctl; next daily run starts cleanly")
requires the merged code on idc02's exec checkout
(`~/CascadeProjects/chaba`, synced by chaba-repo-sync.timer). This dispatch
is worktree-confined and cannot touch idc02. After merge:

```
ssh idc02
cd ~/CascadeProjects/chaba && git pull    # or wait for chaba-repo-sync.timer
systemctl --user start embed-lane-banks.service
systemctl --user status embed-lane-banks.service   # expect Result=success
journalctl --user -u embed-lane-banks.service -n 50   # no timeout, "budget ... stopping run cleanly" ok
```

Expected: run exits 0 well under 45 min with a nonzero copied count;
`embed-lane-banks.timer` next fires on its normal daily cadence.

## Why this fix (vs raising TimeoutStartSec)

The backlog is ~71K docs (74940 in ada-ha-bank-devin-handoff alone) at a
queue-throttled copy rate (~15–70 docs/min depending on embed-pool drain).
No finite TimeoutStartSec makes one run finish the backlog; the daily timer
+ resume-safe key-set diff is the designed completion mechanism. The budget
cap converts "SIGTERM kill, Result=timeout, sentinel re-alerts" into
"clean exit 0, incremental progress, cursor advances" — the timer-alert
loop on card timer-alert-idc02-embed-lane-banks should stop reopening this.

## Lessons

- Dispatch branches that fail auto-merge (push to non-bare checked-out
  master refused) lose ALL work — the prior attempt's --budget implementation
  never reached origin/master. Verify `git branch -r --contains` / file
  content on origin before trusting a prior dispatch's DONE comms.
- `systemd/generated/` must equal `render(manifest)` exactly; any manifest
  edit requires a full re-render or GeneratedTree fails on unrelated drift.
- `embed-lane.py banks` queue-throttle wait was unbounded — wall-clock caps
  must cover BOTH the work loop and the wait loop or a saturated queue still
  gets the unit SIGTERMed.
