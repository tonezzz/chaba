# Dispatch outcome — devin-taskdir-gc-dispatch-hosts

Card: `devin-taskdir-gc-dispatch-hosts` (parent: devin-usage-reduction, DEV-1333)
Dispatch: 20261125-094030 on tony-macbook. Commit `97e66a65cb` on
`dispatch/20261125-094030-parent-card-devin-usage-reduct` (not pushed).

## What was found (survey, verified over ssh 2026-11-25)

| host | task dirs | exit_code | sessions.db | prune path before |
|---|---|---|---|---|
| tony-dell | 236 | 204 | 5.2G | NONE — `devin-cleanup.timer` claimed in ssot.devin.maintenance was never installed; only devin-dispatch-prune (worktrees/branches) |
| tony-omen | 392 | 345 | 1.6G | sessions.db only (devin-cleanup.sh python pruner + session-prune.py) — no task-dir GC |
| idc01 | — | — | — | offline ~34d |
| idc02 | 928 | 918 | 1.4G | NONE — no devin timers at all |
| idc03 | 165 | 141 | 176M | NONE for task dirs |
| mn01 | 107 | 97 | 313M | NONE — 1.1G of task dirs |
| con01 | — | — | — | NOT dispatch-capable (no devin CLI, no registry) — excluded |
| tony-macbook | 286 | 278 | 6.0G | devin-cleanup.service → `~/.local/bin/prune-devin-sessions.sh 7` — live bug below |

Root causes: the only task-dir GC ever written was an inline block in
`scripts/prune-devin-sessions.sh` that reused the sessions.db retention
(3–7d) — which would corrupt `devin-usage.py`'s 30d reporting window —
and it was live on tony-macbook via a stale `~/.local/bin` copy. No
ssot.jobs.yml job covered task dirs; repo `systemd/devin-cleanup.*` was
never installed on most hosts.

## What changed

- `scripts/devin/taskdir-prune.py` (new, canonical GC):
  - finished dirs (`exit_code` present) pruned past `--days 45`
    (>= 30d usage window + margin); per-task metrics appended to
    `~/.local/share/devin-dispatch/taskdir-usage.jsonl` before delete.
  - stale no-`exit_code` dirs past `--stale-days 14` only when last
    activity >14d AND no live `devin-task-<id>`/`devin-task-<id>-fu*`
    systemd --user unit AND no `needs-input.txt`.
  - timeline.jsonl audit line per run; `--dry-run`/`--json`.
- `scripts/prune-devin-sessions.sh`: inline GC block replaced with
  non-fatal delegation to `taskdir-prune.py` (45d, not `$RETENTION_DAYS`).
- `scripts/devin/devin-usage.py`: `--fleet` now also scans the invoking
  host locally — ssh-to-self isn't set up on tony-macbook, so the fleet
  report silently missed it (167 sessions now counted).
- `ssot.jobs.yml`: `devin-taskdir-prune` declared for tony_dell,
  tony_omen, idc01, idc02, idc03, mn01, macbook — daily 04:40,
  Persistent, `condition_path` on the script (inert until repo-sync
  delivers it post-merge). con01 deliberately absent.
- `systemd/generated/<host>/devin-taskdir-prune.{service,timer}`
  rendered for all 7 hosts (`render-jobs.py --check`: OK 131 jobs).
- `ssot.devin.maintenance.yml`: new `dispatch_task_dirs` section;
  corrected stale tony-dell (timer never installed, sessions.db 5.2G
  unmanaged) and tony-omen (actual ExecStart is `~/.local/bin/
  devin-cleanup.sh`, a different python script) claims.
- `docs/ssot/jobs/devnest/2026-11-25-devin-taskdir-gc.yml`: full trail.

## Deployed + sweep

`taskdir-prune.py` installed into each host's exec checkout
(`~/CascadeProjects/chaba/scripts/devin/`, untracked until merge —
git-safe-pull's untracked-collision handling covers the transition) and
`devin-taskdir-prune.timer` enabled on dell/omen/idc02/idc03/mn01/
macbook (next fire 2026-11-26 04:40 local). idc01 declared only.
tony-macbook `~/.local/bin/prune-devin-sessions.sh` updated to the repo
version, ending the live 7d task-dir GC.

One-time sweep (finished+stale pruned / kept / freed / ledgered):
- tony-dell: 80 (56+24) / 157 / 25.4MB / 55
- tony-omen: 24 (0+24) / 368 / 0.4MB / 0
- idc02: 36 (27+9) / 895 / 11.6MB / 25
- idc03: 105 (81+24) / 60 / 33.7MB / 74
- mn01: 30 (21+9) / 77 / 6.5MB / 16
- macbook: 0 / 288 / 0 / 0

Total: 275 dirs pruned fleet-wide.

## Verification

- `devin-usage.py --fleet --days 30` before: 500 sessions /
  1,957,761,562 tokens (macbook invisible). After: idc02 still 188
  sessions / 884,877,331 tokens in-window; fleet total 2,609,714,372
  incl. +167 newly-visible macbook sessions. All pruned finished dirs
  were >45d old (outside window); stale dirs >14d inactive per spec.
- `render-jobs.py --check`: OK. `ssot-validate-all.mjs`: 6417 files, 0
  errors. `ssot-prose-smell.py`: clean. Pre-commit SSOT validation passed.
- `systemctl --user list-timers` on each host shows
  devin-taskdir-prune.timer enabled, next 2026-11-26 04:40.

## How to verify

- `systemctl --user list-timers devin-taskdir-prune.timer` on any
  dispatch host; `journalctl --user -u devin-taskdir-prune.service`
  after 04:40.
- `wc -l ~/.local/share/devin-dispatch/taskdir-usage.jsonl` on a swept
  host (ledger grew by finished-pruned count minus unparseable).
- `python3 scripts/devin/devin-usage.py --fleet --days 30` — macbook
  rows now appear; 30d numbers unchanged by the sweep.

## Follow-ups (not done, noted on card/SSOT)

- tony-dell sessions.db (5.2G) has NO cleanup path — devin-cleanup was
  declared but never installed; candidate for a card.
- con01 stays excluded unless a devin CLI is ever installed there.

lessons:
- The only task-dir GC lived inline in prune-devin-sessions.sh keyed to
  the sessions.db retention arg — two different retention domains
  silently shared one knob; devin-usage.py's 30d window made the 7d
  value data-corrupting, not just aggressive.
- Hand-installed ~/.local/bin copies of repo scripts drift silently —
  macbook's copy predated a fix and was actively deleting usage data
  weekly; installed copies need md5 checks like runner-agent drift.
- ssot.devin.maintenance.yml claimed tony-dell devin-cleanup.timer
  coverage that never existed — SSOT service claims need the same
  verify-by-surface discipline as "done" cards.
- devin-usage.py --fleet could never see tony-macbook (no ssh-to-self);
  fleet scanners should always include a local scan of the invoker.
- systemd-run --collect units vanish after exit, so "no live
  devin-task-<id> unit" is a reliable dead-task signal — but only when
  checked on the host that owns the task dir.
