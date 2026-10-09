# Dispatch outcome — jev-bench.service on idc02 retargeted (fix-jev-bench-target)

## What was wrong

`jev-bench.service` on idc02 failed hourly (Connection refused) because its
ExecStart pointed at retired idc01: `jev-bench.py http://100.74.146.0:8778
--mddb http://100.74.146.0:11023/v1 --report-cms`.

Correction to the card's premise: the unit was **hand-installed** on idc02
(2026-10-01 14:43) — no `rendered from ssot.jobs.yml` marker, no job in
`ssot.jobs.yml`, nothing under `systemd/generated/idc02/`. There was no
source to fix; the fix *created* the source.

## Decision: repoint, not retire

- **Live consumer exists** — `scripts/ada/nest-overview.py` (every 30 min
  via chaba-kanban-brief.service) reads the `bench-jev` CMS page into the
  chaba-nest L2 report; auto-report reads `kind:benchmark` docs for
  regressions.
- **Target**: `http://100.102.134.91:8778` — jev-student (prod
  confirm-gate distilbert) on idc03, verified `/health` 200 + live
  `/v1/systemone` noul round-trip. Not idc02's local open-jev :8777 — the
  unit's purpose is "accuracy vs jev-student"; heavy lanes are already
  probed by nest-overview.
- **MDDB**: `http://100.102.134.91:11023/v1` — idc03 **leader**. idc02's
  local :11023 is a read-only follower; writes must go upstream.

## Changes

- `docs/ssot/infrastructure/ssot.jobs.yml` — new `jev-bench` job (host
  idc02, `OnCalendar=hourly`, Persistent, 10m timeout, retarget note).
- `systemd/generated/idc02/jev-bench.{service,timer}` — rendered via
  `scripts/render-jobs.py --host idc02` (`--check`: OK 44 jobs, 7 hosts).
- Installed on idc02 `~/.config/systemd/user/` + `daemon-reload` (timer was
  already enabled; next run 17:00).
- `docs/ssot/jobs/infrastructure/2026-10-09-jev-bench-retarget.yml` — job
  record.

## Verify (done)

- `systemctl --user start jev-bench.service` → `status=0/SUCCESS`:
  10/10 noul correct, 11/18 overall (0.6111), median 0.1s. Tool-routing
  1/8 is expected — jev-student is binary-only and returns a fixed
  'answer' stub (same profile as the pre-retirement series: score
  unchanged at 0.6111, trend continuous).
- `bench/jev-20261009-164053` in ada-ha-scenario-reports, target
  `100.102.134.91:8778`; `bench-jev` CMS page updated 16:40:53.
- `ssot.audit.hosts.yml` idc02 `known_failed` was already `[]` in this
  worktree — the entry was never committed here (likely only in the live
  chaba-tony-dell checkout via `--save-to-ssot`). If it resurfaces there,
  drop it — the unit is healthy.

## Leftovers noted (not in scope)

- `jev-retrain.timer` on idc02: enabled but inactive; `jev-retrain.sh`
  harvests corpus from and deploys to idc01 — dead pipeline until
  retargeted at idc03. Card material.
- `ssot.nest-brains.yml` jev-student entity still lists `idc01:` paths —
  stale metadata.
- `ada-pi-orch-bench` in ssot.jobs.yml: exec renders verbatim (relative
  path + `", then …"`). The *deployed* tony-omen unit is hand-maintained
  and works (has WorkingDirectory + lane start/stop guards) —
  `render-jobs.py --host tony_omen --install` would clobber it with a
  broken unit. Treat that exec string as documentation.
