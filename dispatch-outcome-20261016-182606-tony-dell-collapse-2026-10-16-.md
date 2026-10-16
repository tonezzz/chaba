# Dispatch outcome — tony-dell podman-lock-wedge (verify, attempt 2)

Card: `tony-dell-podman-lock-wedge` (OPS-0718, `review_kind: verify`)
Prior attempt left no artifacts (no commits on the dispatch branch, no
outcome doc, card comms untouched) — this run is effectively the first
verify pass, not a retry of a failed approach.

## What was verified (on tony-dell itself)

- **Host recovered.** Up 4h at check time; `timeout 10 podman ps` returns
  19 running containers instantly; only transient MCP `docker ps` calls
  observed; load declining (4.68 →), swap 4.3G/15G is post-thrash residue
  draining lazily. `/dev/shm/libpod_rootless_lock_1000` exists but is the
  live lock recreated at boot — tmpfs clears every reboot.
- **The pile-up fix is real and running.** Commit `aa879d254`
  ("monitoring-dashboard: bound docker-ps health checks", 2026-10-16
  14:35 +07) is an ancestor of `origin/master`; the served copy at
  `~/CascadeProjects/chaba-tony-dell/scripts/monitoring-dashboard.mjs`
  is byte-identical; running process PID 48190 (started post-boot) uses
  it. Old code: 4 unbounded `docker ps --filter name=` per 30s tick.
  New: one `timeout 8 docker ps` for all containers + exec timeout 10s
  SIGKILL.
- **Sibling callers audited — all bounded:** `scripts/ada/host-services-cms.py`
  (subprocess timeout=90s, on-demand), `~/.local/bin/tony-dell-monitor.sh`
  (curl `--max-time` + subprocess timeout=10, no podman calls),
  `scripts/system-maintenance.mjs` (execSync timeout=300s, manual),
  `mcp-servers/mcp-health/server.js` (on-demand MCP calls, no timer loop).
  The fast-timer + unbounded-exec combo was unique to monitoring-dashboard.
- **Mitigations present:** earlyoom active, 8G zram swap ahead of the
  5400rpm disk swap — neither prevented collapse (process-count-driven
  exhaust), noted in the doc.

## Residual gap found → carded

Stale-lock recovery is still manual — nothing detects a wedged rootless
podman state DB mid-session. Filed `podman-lock-wedge-watchdog`
(OPS-0726, backlog) via board-api: 2-min probe timer (`timeout 8 podman
ps`), N≥3 failures + no live podman CLI → auto-clear stale locks per the
runbook + alert. Also noted: `overnight-jobs-expanded.sh` has ~11
unbounded sequential `docker ps` calls — capped pile of 1, low priority.

## Deliverables

- `docs/ssot/jobs/infrastructure/2026-10-16-tony-dell-podman-lock-wedge.yml`
  — incident record: summary, timeline (messy 10-14 boot → wedge →
  700-proc pile → thrash → 14:23 reboot → 14:35 fix), findings, embedded
  `recovery_runbook` (probe → confirm dead lock holder → clear shm lock /
  pause.pid / alive.lck → `podman system renumber` → re-probe; reboot
  first if already thrashing), followups, verification commands.
  Committed as `895a241e3` on the dispatch branch.
- Follow-up card `podman-lock-wedge-watchdog` (OPS-0726).
- Card comms: verify PASS summary posted.

## How to verify

```
timeout 10 podman ps | wc -l                      # ~19, instant
diff -q scripts/monitoring-dashboard.mjs \
  ~/CascadeProjects/chaba-tony-dell/scripts/monitoring-dashboard.mjs
git merge-base --is-ancestor aa879d254 origin/master
ps -eo pid,etimes,args | grep monitoring-dashboard   # PID 48190 post-boot
```

lessons:
- /dev/shm is tmpfs: a stale libpod rootless lock never survives reboot — the lock was orphaned mid-uptime by an unclean podman kill; reboot clears it, so don't hunt for boot-time cleanup mechanisms.
- The dangerous pattern is fast-timer + unbounded exec fan-out; audit siblings by checking each caller's exec timeout AND its invocation cadence, not just the presence of `docker ps`.
- Swap-thrash boxes stop logging before they stop responding — journal had zero wedge evidence; corroborate via commit messages, code diff, and post-hoc state instead.
- `git log master..HEAD` in a dispatch worktree can mislead (local master may lag origin/master); compare against `origin/master` before concluding attempt-1 left commits.
