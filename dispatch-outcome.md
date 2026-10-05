# dispatch outcome — devin-session-prune

Built the dispatch-era session prune job for tony-dell, verified it end to
end, and installed the weekly timer.

## Deliverables (commit c4163d6a on dispatch/20261005-143056-…)

- `scripts/devin/session-prune.py` — the job. Prunes sessions.db rows older
  than `--days` (14) ONLY when they're provably dispatch-era: dispatch prompt
  title prefix, `dispatch-wt-<task_id>` worktree + `~/.local/share/
  devin-dispatch/tasks/<task_id>/` meta, or a `resume/<sid>` task branch.
  Interactive sessions are never candidates. Keep-guards: live session lock,
  `needs-input.txt`, dirty/unmerged/unreadable worktree, recorded branch with
  commits not in master/main. Deletes child tables first (incl.
  `prompt_history`, which the older blunt prune orphaned). Each pruned
  session id+title → `~/var/chaba/reports/timeline.jsonl` via
  `scripts/lib/report.py`; a run-complete summary event follows.
- Integrity guard: pre-delete `quick_check` runs against a tmpfs
  sqlite-backup snapshot — a live check measured 200MB/12min on the busy HDD
  (2.1G db + ~1G WAL); snapshot does the same coverage in ~3min. `--skip-check`
  escape hatch included.
- Vacuum: reuses devin-vacuum-when-closed.sh's two-clear-checks (no
  `devin-desktop|devin acp` + no fuser, twice consecutively) plus the
  watchdog-flag rename; then runs repo `scripts/devin/session/vacuum-devin-db.sh`
  (fallback `~/.config/devin/scripts/`). Skips cleanly when Devin is open.
- `docs/ssot/infrastructure/ssot.jobs.yml` — new job `devin-session-prune`
  (Sun 03:00, Persistent, 30m); rendered units in
  `systemd/generated/tony_dell/`.
- `docs/ssot/jobs/infrastructure/2026-10-05-devin-session-prune.yml` — trail
  doc with the full decision record.

## Install state

Timer installed + enabled on tony-dell: next elapse **Sun 2026-10-11 03:00
+07**. NOTE: the unit's ExecStart is `%h/CascadeProjects/chaba/scripts/devin/
session-prune.py` — resolves once this branch merges; merge must land before
the first fire.

## Verification

- `--dry-run` + real run on a sqlite-backup snapshot: 83/164 sessions
  dispatch-era → 56 pruned / 27 kept (active-lock, worktree-dirty,
  worktree-git-unknown, branch-unmerged all exercised); sessions 164→107,
  message_nodes 204242→168877, zero orphans in FK'd tables.
- Real run on the live DB: 0 candidates (the Sun-04:00 `devin-cleanup.timer`
  already deletes everything >7d — see caveat). Vacuum correctly skipped
  while a devin session held the DB; timeline event confirmed.
- `devin 3000.10.35` opens; live `PRAGMA integrity_check` launched
  (HDD-slow; snapshot quick_check already passed clean).

## Caveat for Tony

`devin-cleanup.timer` (Sun 04:00) deletes **all** sessions >7d, dispatch or
not — so this job's 14-day window and keep-guards currently overlap
nothing. If the guards should actually protect dispatch sessions up to 14d,
retune or retire the blunt timer (one hour after this job).
