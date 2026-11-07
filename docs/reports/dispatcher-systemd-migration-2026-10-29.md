# Dispatcher → systemd rendered-timer migration (OPS-0790)

Date: 2026-10-29 · Card: `dispatcher-jobs-systemd-migration-ops0790` ·
Parent: `chaba-jobs-dispatcher-dead-fleet-wide-di-765e5b` (OPS-0790)

## Decision being executed

chaba-jobs.timer (the 1-min dispatcher tick) was found inactive fleet-wide on
2026-10-23 — every `dispatch: dispatcher` job had silently stopped running.
Tony's approved option on the card's decision request: *"Migrate all remaining
dispatcher jobs to use dispatch:systemd rendered timers (like nest-queue-watch)
and remove the legacy dispatcher."*

This report covers the **code/registry phase only**. No timers were installed
or enabled, and the live `chaba-jobs.timer` units were not touched — that is a
separate deploy-lock rollout (see *Rollout* below).

## Per-job mapping

All eight remaining `dispatch: dispatcher` entries in
`docs/ssot/infrastructure/ssot.jobs.yml` were converted to
`dispatch: systemd`. Field mapping is verbatim; cadence stays `every:` which
the renderer emits as `OnBootSec=1min` + `OnUnitActiveSec=<interval>`.

| job | host | every | timeout | rendered units | notes |
|---|---|---|---|---|---|
| embed-lane-news | idc03 | 1h → `OnUnitActiveSec=60min` | 5m → `TimeoutStartSec=300` | embed-lane-news.{service,timer} | env_file + condition_path now effective (E1) |
| embed-lane-lessons | idc03 | 1d → `OnUnitActiveSec=1440min` | 10m → `TimeoutStartSec=600` | embed-lane-lessons.{service,timer} | same as above |
| embed-lane-banks | idc02 | 1d → `OnUnitActiveSec=1440min` | 45m → `TimeoutStartSec=2700` | embed-lane-banks.{service,timer} | condition_path now effective (E1) |
| yomi-update-active | idc03 | 15m → `OnUnitActiveSec=15min` | 120s → `TimeoutStartSec=120` | yomi-update-active.{service,timer} | podman `--name` preclean preserved via renderer `ExecStartPre` (E4) |
| mcp-debug-h3-sync | tony_dell | 10m → `OnUnitActiveSec=10min` | 60s | mcp-debug-h3-sync.{service,timer} | field-for-field, no extras |
| tony-dell-health-snapshot | tony_dell | 5m → `OnUnitActiveSec=5min` | 60s | tony-dell-health-snapshot.{service,timer} | field-for-field |
| network-scan-tony | tony_dell | 15m → `OnUnitActiveSec=15min` | 120s | network-scan-tony.{service,timer} | `critical: false` dropped — isolation is inherent (E2) |
| lesson-drift-check | tony_dell | 1d → `OnUnitActiveSec=1440min` | 90s | lesson-drift-check.{service,timer} | field-for-field |

Field-by-field contract:

| manifest field | dispatcher behavior | systemd rendered equivalent | status |
|---|---|---|---|
| `host` | chaba-jobs tick on that host | units emitted under `generated/<host>/` | preserved |
| `every` | interval check vs `state.json` last_run | `OnBootSec=1min` + `OnUnitActiveSec` | preserved (see E5 re catch-up) |
| `timeout` | `subprocess.run(timeout=)` → SIGKILL | `TimeoutStartSec` → systemd kill | preserved |
| `cwd` | subprocess cwd | `WorkingDirectory=` | preserved |
| `exec` (string) | `shell=True` single command | `ExecStart=` (no shell) | preserved — all 8 execs are metachar-free |
| `exec` (list) | joined with `&&` | one `ExecStart=` per entry (chain on success) | preserved (none of the 8 used lists) |
| `env_file` | **ignored by job-dispatcher** | `EnvironmentFile=` | becomes effective (E1) |
| `env` map | merged into child env | `Environment=` lines | preserved (unused by these 8) |
| `condition_path` | **ignored by job-dispatcher** | `ConditionPathExists=` (skip, not fail) | becomes effective (E1) |
| `critical: false` | isolate + backoff + results record + 1 inbox alert/episode | per-unit isolation + journald + timer-sentinel card | mapped (E2) |
| results record | append to `~/var/chaba/reports/timeline.jsonl` | journald + timer-timeline ledger | delta (E3) |
| failure backoff | exponential ×2, cap 4h | none — next scheduled run | delta (E6) |

## Exceptions and deltas

- **E1 — `env_file`/`condition_path` were dead fields under the dispatcher.**
  `job-dispatcher.py` never read either key; only the renderer implements
  them. Under systemd they now actually apply. For the embed-lane jobs this
  is safe: `embed-lane.py` already self-loads
  `~/.config/secrets/litellm-chaba.env` as a fallback (`litellm_creds()`),
  and `condition_path` points at the script itself which must exist for the
  job to work at all. Net effect: config now does what it always claimed.
- **E2 — `critical: false` (network-scan-tony) is dropped from the manifest.**
  The flag only exists for `dispatch: dispatcher`. Under rendered timers the
  guarantee it encoded — "a --push crash must not starve sibling jobs" — is
  structural: each job is its own oneshot unit; a failure marks only that
  unit. Alerting moves from the dispatcher's once-per-episode focus-inbox
  entry to `timer-sentinel`, which already files deduped `timer-alert-*`
  kanban cards for any failing expected timer fleet-wide.
- **E3 — results ledger changes.** Dispatcher jobs appended
  `{name, command, ok, exit_code, duration_ms, ts}` to
  `~/var/chaba/reports/timeline.jsonl` (surfaced in report-system's
  recent-timeline section). Rendered timers log to journald instead, and
  `timer-timeline-update.py`'s 15-min fleet sweep already records last-run
  result/duration per timer — the live observability surface for these jobs.
  The per-host `state.json` under `~/var/chaba/jobs/` becomes orphaned after
  rollout; harmless to leave.
- **E4 — podman stale-`--name` preclean is now renderer-emitted.**
  `job-dispatcher.run_job` pre-ran `podman rm -f <name>` for every exec
  containing `podman` + `--name`, guarding the OPS-0531 wedge (timeout-killed
  run orphans the named container → all later runs exit 125 forever).
  `render-jobs.py` now emits `ExecStartPre=-/usr/bin/podman rm -f <name>`
  (best-effort `-` prefix) for any exec carrying `podman … --name`. This
  also closes the same latent gap on the already-migrated `yomi-update-all`,
  whose service gains the preclean on this render.
- **E5 — no `persistent:` added.** `Persistent=true` only applies to
  `OnCalendar=` timers; for `every:`-rendered monotonic timers it is a no-op,
  so it was deliberately left off to keep the mapping 1:1. Catch-up
  semantics differ slightly from the dispatcher (which fired immediately on
  restart if the interval had elapsed): under `OnBootSec`+`OnUnitActiveSec`
  the unit refires 1 min after boot and then on cadence — equivalent
  coverage for periodic-refresh jobs, without a catch-up burst.
- **E6 — no exponential backoff.** The dispatcher's ×2 backoff (cap 4h) is
  not replicated; a failing job retries at its normal cadence. Accepted per
  the rendered-timer contract (isolation + sentinel alerting carry the
  failure story). If a specific job needs retry shaping later, that's a
  per-job `OnCalendar=`/wrapper decision, not a registry-level one.
- **E7 — `chaba-jobs.timer` not removed.** With zero `dispatch: dispatcher`
  entries, `render_host` no longer emits `chaba-jobs.{service,timer}` for any
  host; the stale generated copies were deleted from
  `systemd/generated/{idc03,tony_dell}/`. The *live* units stay untouched
  until every replacement timer is installed and verified — disabling them
  early would leave zero coverage while the new timers are absent.
- **E8 — generated tree reconciled.** Re-rendering surfaced 70 stale units
  in `systemd/generated/` that no longer match the manifest (jobs moved to
  con01/idc03/etc. without cleanup, plus the retired chaba-jobs pair). All
  were deleted; the new `GeneratedTree` test now fails CI if the committed
  tree ever diverges from the manifest again.
- **E9 — audit census deferred to rollout.** `ssot.audit.hosts.yml` already
  expects `mcp-debug-h3-sync`, `network-scan-tony`, `tony-dell-health-snapshot`,
  and `yomi-update-active` timers. `embed-lane-*.timer` and
  `lesson-drift-check.timer` are *not* declared — adding them now would make
  timer-sentinel card them as missing before install. Declare during rollout
  once each timer is armed.

## Code changes

- `docs/ssot/infrastructure/ssot.jobs.yml` — 8 entries converted; notes
  record the migration + E1/E2/E4 caveats.
- `scripts/render-jobs.py` — `render_service` emits
  `ExecStartPre=-/usr/bin/podman rm -f <name>` for exec strings containing
  `podman` + `--name` (E4).
- `systemd/generated/` — re-rendered; 70 stale units removed, 16 new
  migrated units + con01 set added, `yomi-update-all.service` gains the
  preclean (1-line diff).
- `tests/ops/test_render_jobs.py` — new, 16 tests: manifest pins (zero
  dispatcher jobs, host/dispatch assertions), per-field preservation in
  rendered units, podman preclean matrix, contract guards (`critical:true`
  still rejected on systemd jobs; `dispatch: dispatcher` path still renders
  tick units for any future use), and the generated-tree parity check (E8).

## Verification

```
python3 -m unittest tests.ops.test_render_jobs tests.ops.test_job_dispatcher
# 28 tests OK
python3 scripts/render-jobs.py --check   # OK 87 jobs, 8 hosts
node scripts/ssot-validate-all.mjs       # 3278 files, 0 errors
```

## Rollout (separate deploy-lock dispatch)

1. On each target host: merge this worktree, `python3 scripts/render-jobs.py
   --host <h> --install` on the exec checkout, `systemctl --user
   list-timers <id>.timer` + one forced `systemctl --user start <id>.service`
   per job to verify.
2. Add the three missing census entries (E9) to `ssot.audit.hosts.yml` as
   timers come up.
3. Only after all eight are installed and verified: `systemctl --user
   disable --now chaba-jobs.timer` on idc03 + tony_dell, then remove
   `scripts/job-dispatcher.py` + `config.dispatcher*` block and the
   `dispatcher` branch of `render-jobs.py` in a cleanup commit.
