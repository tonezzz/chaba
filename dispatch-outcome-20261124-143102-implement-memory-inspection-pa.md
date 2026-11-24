# Dispatch outcome — memory-inspect-pages (MEM-0745, retry/verify pass)

## Situation found

This retry was a duplicate of already-landed work. The implementation
merged to origin/master on 2026-11-23 via `b70550b9`
(`b12887a4b5b` + `1f496e22609` — `scripts/ada/bank-inspect.py`,
`apps/cms-render` memory-inspect kind/template/collections,
`ssot.jobs.yml` daily job, rendered units, tests). Tony triaged the
card closed on merged evidence at 14:23, then requested a retry at
14:29 — this run is that retry, so it ran as a verification pass and
closed the one remaining gap instead of re-implementing.

## What this run did

- **Verified merge state**: both commits are ancestors of
  `origin/master`; tony-dell's exec checkout
  (`~/CascadeProjects/chaba`) contains `1f496e22609` and
  `scripts/ada/bank-inspect.py`.
- **Test suite**:
  - `tests/ada/` — **377 passed** (needs a venv with
    `apps/cms-render/requirements.txt` + `httpx` + `pillow` +
    `websockets`; `--system-site-packages` venv works).
  - Merge-gate set `REPO_TESTS["chaba"]` — **247 passed** in 61s.
- **Snapshot generation**: `bank-inspect.py --dry-run` from idc02
  produced all 4 lane page sets (kk/-kk, kk-dev/-kk-dev,
  michael/-mn, tony/-pages), exit 0.
- **Closed the remaining gap — armed the daily timer on tony-dell**:
  the generated units existed in the repo but were never installed
  (`systemctl --user status bank-inspect.timer` → not found).
  Ran `python3 scripts/render-jobs.py --host tony_dell
  --ids bank-inspect --install` in tony-dell's checkout → wrote
  `~/.config/systemd/user/bank-inspect.{service,timer}`, enabled the
  timer (dispatcher meta-units untouched per OPS-0790).
- **Live service verification on tony-dell**:
  `systemctl --user start bank-inspect.service` → `Result=success`,
  `ExecMainStatus=0`, 21s wall — published all **37 pages**
  (tony 15, kk 8, kk-dev 9, michael 5), zero publish failures.
  Timer next run: **2026-11-25 05:40 +07**, `enabled`.
- **Consumer surface**: `http://100.102.134.91:8010/p/memory-inspect`
  → 200 ("Memory inspect — tony lane"), leaf pages 200;
  `/p/memory-inspect-devin` renders the full entry table incl.
  `*(redacted)*` markers; index links all 15 tony-lane pages.
- **Runbook updated**: `docs/ssot/jobs/ada/2026-11-23-memory-inspect-pages.yml`
  `schedule.armed` records the install command, first scheduled run,
  and the successful manual service run.

## Changed files (this worktree)

- `docs/ssot/jobs/ada/2026-11-23-memory-inspect-pages.yml` — armed note
- `dispatch-outcome-20261124-143102-implement-memory-inspection-pa.md` — this file

No code changes were needed — the feature was already complete on
master; the only missing piece was the systemd install, done live on
tony-dell (reversible: `systemctl --user disable --now
bank-inspect.timer`).

## How to verify

- `ssh tony-dell 'systemctl --user list-timers bank-inspect.timer'`
- `ssh tony-dell 'journalctl --user -u bank-inspect.service -n 50'`
- `python3 -m pytest tests/ada/ -q` (in a venv with cms-render reqs +
  httpx/pillow/websockets)
- Open `http://100.102.134.91:8010/p/memory-inspect`

## Notes / not done

- cms-render on idc03 may still run pre-merge code → pages fall back
  to the generic page template until the next cms-render deploy; the
  dedicated `memory-inspect` kind dispatch + "Memory" index section
  activate then. Pages themselves render correctly either way.
- `ada-cms-pages` MDDB `/search` caps at 1000 docs — memory-inspect
  pages in the tony collection sit beyond the cap; verify by key or
  via the render surface, not collection scans.

lessons:
- A retried dispatch can arrive after the card already merged AND
  closed — check `git merge-base --is-ancestor <commit> origin/master`
  and card comms before re-implementing; the right move is verify +
  close remaining gaps.
- `render-jobs.py --install` runs systemctl LOCALLY — it must be run
  on the target host inside that host's repo checkout, not from the
  dispatch worktree.
- tests/ada needs more than cms-render requirements: `httpx`
  (map_embed), `pillow`+`websockets` (kk_degraded_mode materializes
  ada-voice backend) — use `python3 -m venv --system-site-packages`.
- `systemctl --user start <oneshot>` blocks until completion and
  returns the unit's result — good enough for live verification.
