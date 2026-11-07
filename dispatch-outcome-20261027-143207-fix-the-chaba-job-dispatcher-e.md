# Dispatch outcome — fix chaba job dispatcher failure isolation

Card: `fix-chaba-jobs-network-scan-failure-isolation` · Runner: tony-macbook · 2026-10-27

## What was wrong

`scripts/job-dispatcher.py` (driven by `chaba-jobs.timer`, 1-min tick) only
recorded `last_run` on success. A failing job — `network-scan-tony` crashing
inside `network-scan.py --push` at a `check=True` subprocess — stayed "due"
forever, was retried every tick, and its failure put the job in `failed[]`
so the service exited 1 every minute. Other due jobs did still run, but any
dispatcher-level exception (bad `cwd`, pre-clean crash) would have aborted
the whole loop mid-tick.

## What changed

- **`scripts/job-dispatcher.py`** — refactored into a testable `tick()`:
  - Per-job try/except isolation: subprocess failure, timeout (exit 124),
    or dispatcher-level error (exit 70 = EX_SOFTWARE) is recorded per job
    and the loop continues — one bad job can't starve the tick.
  - Exponential backoff: `interval * backoff_factor**(failures-1)`,
    floored at the job's own interval (first failure retries on normal
    cadence — not a silent disable), capped at
    `config.failure_policy.backoff_cap` (4h, factor 2). Cap never goes
    below the interval.
  - State per job now persists `last_run`, `last_success`, `last_failure`,
    `failure_count`, `next_retry`, `alerted`, `ok`, `exit_code`.
    Old-format state migrates transparently.
  - Results timeline record gains `critical`, `failure_count`,
    `backoff_s`, `err` (stderr tail) — evidence preserved per attempt.
  - Alert: first failure of an episode files ONE focus-inbox entry via
    board-api `/inbox` (high if critical, else medium); unreachable API
    degrades to local `docs/ssot/focus-inbox/job-fail-<host>-<jid>.yml`,
    self-healed (unlinked) on recovery. Success resets the flag so a new
    episode re-alerts.
  - Exit policy: exit 1 iff a `critical: true` job failed; noncritical
    failures never fail `chaba-jobs.service`.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — `config.failure_policy`
  (`backoff_factor: 2`, `backoff_cap: 4h`), new `critical:` convention
  (dispatcher-only, default false), `network-scan-tony` annotated with
  explicit `critical: false` + note.
- **`scripts/render-jobs.py`** — `--check` validates `critical` is a bool
  and only appears on `dispatch: dispatcher` jobs.
- **`tests/ops/test_job_dispatcher.py`** — 12 tests: fail+ok same tick,
  dispatcher-exception containment, backoff floor/doubling/cap, reset on
  success, state persistence across ticks, results-record fields, exit
  policy (noncritical→0 / critical→1), alert once-per-episode + file
  fallback + self-heal, dry-run purity.
- **`docs/ssot/jobs/infrastructure/2026-10-27-job-dispatcher-failure-isolation.yml`**
  — runbook/verdict trail.

## Verification

- `python3 -m unittest tests.ops.test_job_dispatcher` — 12/12 pass
  (19/19 with the neighboring podman-lock-watchdog suite).
- `python3 scripts/render-jobs.py --check` — OK, 87 jobs / 8 hosts.
- `python3 scripts/job-dispatcher.py --host tony_dell --dry-run` — 4 due
  jobs listed; `--host idc03 --dry-run` — 3; no state/results writes.
- `python3 scripts/ssot-validate-refs.py` — 3144 files, no broken refs.

## Not done / notes

- Network scanning is NOT disabled — `network-scan-tony` keeps its 15m
  cadence, backs off on failure to a 4h ceiling, and alerts once per
  episode via focus-inbox.
- Follow-up worth a card: dispatcher ignores manifest `env_file` /
  `condition_path` today (`embed-lane-news` on idc03 declares
  `env_file: litellm-chaba.env` that never gets loaded).
- Deploy: nothing pushed/deployed from this worktree. Once merged, the
  tony_dell exec checkout picks it up via `chaba-repo-sync.timer`; no unit
  re-render needed (`chaba-jobs.service` ExecStart unchanged). Existing
  `state.json` on dell upgrades in place — network-scan's first failure
  after the merge files one alert instead of hammering every minute.
