# Dispatch outcome — session-capture-d1-metrics (attempt 2)

## Result

All card deliverables were already landed on master by the OPS-1368 salvage
commit `566ed29e07` ("capture Phase D follow-ups + recover d1-metrics
artifacts"), which recovered the prior attempt's uncommitted worktree files.
This attempt verified the artifacts against the card's acceptance criteria —
no new code changes were needed and the worktree is clean.

## Verified deliverables

- `reports/capture/metrics-20261125.md` — read-only capture-metrics.py report:
  repeat-ask 15 asks / 13.12 per week / register 34d stale; miss rate 0 since
  2026-11-23 instrumentation; stale-pointer proxy 35 candidates >30d
  (oc-note 32, ssot 3); time-to-find 3 real info_find.py samples, median
  1647ms; matrix precision 100% on regenerated ledger.
- `docs/ssot/jobs/kanban/2026-11-25-session-capture-d1-metrics.yml` — job doc
  recording goal, delivered artifacts, verify commands, and the no-fake-events
  posture (3 time-to-find samples are real `info_find.py run` invocations;
  stale-pointer stays labelled proxy).
- `docs/ssot/ssot.knowledge-capture.yml` — "Phase D Refresh (2026-11-25)"
  section with measured values, the ledger-durability gap note, and recorded
  tuning thresholds (repeat-ask >14d stale, misses/week >2, pointer
  candidates >30, time-to-find median >5000ms or resolved <80% over >=20
  runs, matrix precision <90% over >=50 creates).
- `reports/capture/capture-ledger.yml` is intentionally NOT committed
  (`.gitignore` `reports/*`); the canonical ledger lives on idc02 under
  `~/.local/share/chaba/capture/` with a declared daily
  `chaba-capture-harvest` job (per OPS-1368 resolution).

## Acceptance check

- Read-only report: yes — metrics report + job doc only.
- SSOT thresholds/tuning: yes — recorded in ssot.knowledge-capture.yml
  Phase D Refresh section.
- No fake events: yes — documented in job doc notes; proxy/measured labels
  are explicit in the report.

## How to verify

```
git log --oneline -1 566ed29e07
sed -n '1,60p' reports/capture/metrics-20261125.md
grep -n "Phase D Refresh" docs/ssot/ssot.knowledge-capture.yml
```

## Prior failure explanation

Attempt 1 produced the files but the checkpoint commit failed during SSOT
validation, leaving the worktree dirty; merge-sweep salvaged them via the
OPS-1368 follow-up card on idc02.

lessons:
- Dispatch checkpoint commits can fail at the SSOT-validation pre-commit step and leave a dirty worktree that merge-sweep may not recover — if a prior attempt "reported done" but produced no commits, check for a salvage commit (e.g. OPS-1368) before redoing the work.
- `reports/*` is gitignored in chaba; report artifacts under reports/ need explicit force-add or an exception — verify `git ls-files` before assuming a deliverable landed.
