# Dispatch outcome — report-graph producer metas never reach con01 renderer

Card: `report-graph-producer-metas-never-reach-7b0982`
Runner: tony-omen · 2026-11-18

## What was done

**Durable fix (option a) — meta-pull step in con01's render chain, live:**

- New `scripts/report/pull-report-metas.sh`: `rsync -au` (newest-mtime-wins,
  recursive `meta*.yml`, renderer-owned `meta.system-report.yml` +
  `meta.focus-inbox.yml` excluded) from every checkout that can hold producer
  metas — idc03 served/exec/kanban-sync, idc02 x2, tony-dell x2, tony-omen,
  mn01, idc01 — plus `tony-dell:~/var/chaba/health/meta.yml` → same absolute
  path on con01. Every source soft-fails; an unreachable host never blocks the
  render.
- `ssot.jobs.yml` `chaba-system-report` exec now runs the pull between
  `--consolidate` and `report-system.py`; note updated. Unit re-rendered
  (`systemd/generated/con01/chaba-system-report.service`), installed on con01,
  daemon-reloaded. Script scp'd into con01's checkout (untracked until this
  worktree merges — con01's `git-safe-pull.sh` resolves the collision
  upstream-wins).
- `_is_local` in `scripts/audit-hosts.py` generalized (was hardcoded
  tony-omen/tony-dell) — `audit-hosts/con01` audited itself over ssh and was
  permanently "unreachable" since the renderer moved to con01.

**Verified end-to-end:** pull + `report-system.py` run on con01 ~10:44 CET;
served `system-report.yml` on idc02 refreshed. Counts went
**missing 20→0, stale ~23→1** — `ok=14 delta=17 planned=2 error=1 stale=1
untracked=1`. Remaining badness is genuine producer state, not transport:
`overnight-assessment=error` (health_snapshot step fails on idc03 — real bug),
`systemwide-assessment=stale` (manual Ada+Devin page unpublished since
2026-09-27 — staleness is the intended signal), `lane-savings=untracked`
(manual producer, no meta writer).

## Stale-producer investigation (second issue) — mostly transport, some real

The ~Oct-23 "stale" wave was an artifact: the earlier manual rsync (no `-u`)
copied idc02's frozen snapshot over con01's own fresh metas. Producers were
alive on idc03's served checkout all along. Real gaps found + fixed:

- `board-janitor.timer` + `fleet-jobs-report.timer` on idc03 — declared in
  ssot.jobs.yml + generated, **never installed**. kanban-stats had no
  scheduled producer since ~Nov-12; fleet-jobs-report was the last `missing`.
  Both installed + enabled; fleet-jobs-report produced meta on first run,
  board-janitor's kanban-stats wrote a fresh kanban meta (its tick exits 1 on
  a `backlog-audit` sub-check error — pre-existing script issue, doesn't
  block).
- `model-bench.timer` on tony-omen — rendered Oct-23, **never enabled**, zero
  runs. Enabled + started (fires Sun 05:15).
- con01 had no ssh known_hosts entries for tony-omen/mn01/itself — audit
  marked them unreachable daily and the pull couldn't reach them. Keys
  verified via independent vantages and added (backup at
  `~/.ssh/known_hosts.bak-20261118`).

**Not touched (needs Tony's call):** tony-dell's leftover
`chaba-system-report.timer` still renders daily into the frozen
chaba-tony-dell mirror (duplicate renderer — arguably useful redundancy since
dell reaches hosts con01 can't). Stale push-back targets left in place (all
are inside the pull set): run-and-ship SERVED + report-feed → dell mirror,
model-bench/route-health/cms-reflect → idc02 exec.

## Files changed

- `scripts/report/pull-report-metas.sh` (new)
- `docs/ssot/infrastructure/ssot.jobs.yml` (exec + note)
- `systemd/generated/con01/chaba-system-report.service` (re-rendered)
- `scripts/audit-hosts.py` (`_is_local` generalized)
- `docs/ssot/infrastructure/ssot.reports.yml` (contract + schedule notes)
- `docs/ssot/jobs/infrastructure/2026-11-18-report-meta-pull.yml` (full
  source map, findings, audit)

## How to verify

- `ssh con01 'cd ~/CascadeProjects/chaba && bash scripts/report/pull-report-metas.sh'`
- `curl -s https://idc02.taila0626a.ts.net/apps/system-report/data/system-report.yml` → `status_counts`
- `systemctl --user list-timers` on idc03 (board-janitor, fleet-jobs-report),
  tony-omen (model-bench)
- Tomorrow's 06:45 CET timer run is the real soak — journal:
  `ssh con01 'journalctl --user -u chaba-system-report.service -n 40'`
