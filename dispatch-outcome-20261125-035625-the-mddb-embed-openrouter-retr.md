# Dispatch outcome — ops-retry-storm-detection (attempt 2)

## What changed

Rebuilt the deliverable that attempt 1 wrote but never committed
(worktree was 107 commits behind origin/master; merge-sweep found it
dirty and dropped it). This attempt lands it as commit `0f3056f87d` on
`dispatch/20261125-035625-the-mddb-embed-openrouter-retr`:

- `scripts/ops/retry-storm-watch.py` — periodic detector, three checks:
  - **cpu**: streams `podman stats` for 6s/tick, keeps the last row per
    container (true interval CPU% — `--no-stream` reports a
    lifetime-ish average). Container >50% CPU accumulates `hot_since`
    in `~/.local/state/retry-storm-watch.json`; alert only after the
    streak reaches 30min — one hot sample never pages.
  - **logs**: `podman logs --since 60m --tail 50000` per running
    container (stderr merged into stdout — WARN/ERROR usually lands on
    the container's stderr stream). Lines matching
    WARN|ERROR|ERR|FATAL|CRITICAL are normalized (hex/ids/numbers
    stripped) into signatures; any signature x30+ alerts — the
    'embedding attempt failed' retry-storm shape.
  - **mddb** (idc03 only): GET `/v1/vector-stats` + `/metrics` per
    `MDDB_WATCH_URLS` base URL, sums numeric counters matching
    drop|error|retr|fail|reject|queue, alerts when the sum climbs >=10
    since the previous tick. First tick only baselines; a fully
    unreachable MDDB returns None and keeps the old baseline so recovery
    can't fake a delta.
  - Findings POST to board-api `/inbox` (priority high, deduped 6h per
    condition), never Telegram per noise policy. Exit 0 healthy / 1
    when alerting — same contract as netdata-nodes-watch.
- `docs/ssot/infrastructure/ssot.jobs.yml` — six `dispatch: systemd`
  jobs, `every: 10min`, `persistent: true`, `timeout: 4m`: idc03 runs
  all three checks with `MDDB_WATCH_URLS=http://127.0.0.1:11023,
  http://127.0.0.1:11027`; idc02, tony_dell, tony_omen, mn01, con01 run
  `--checks cpu,logs`.
- `systemd/generated/<host>/retry-storm-watch.{service,timer}` —
  rendered units committed for all six hosts.
- `docs/ssot/jobs/monitoring/2026-11-25-retry-storm-watch.yml` — trail
  doc (decision, verification, deploy steps, follow-ups).

## Verified

- `py_compile` clean; live `--no-alert` run on this host: 5 containers
  sampled (xmeye-vms-vnc 31% correctly below the 50% threshold), exit 0.
- MDDB leg verified over tailnet against the live leader
  (100.102.134.91:11023): baseline score=28068 established; dead URL
  correctly skipped without poisoning the baseline.
- `render-jobs.py --check`: OK 133 jobs, 8 hosts; units rendered for
  all six hosts; pre-commit SSOT validation passed.
- Prior attempt's live dry-run on idc03 already proved the log
  signature check against real data: 'embedding attempt failed' x119
  (mddb) + x78 (mddb-cms) in 60m.

## Not done (by design)

Units are NOT installed — dispatch rules forbid deploy. After merge +
each host's chaba-repo-sync pull, run
`python3 scripts/render-jobs.py --host <h> --ids retry-storm-watch --install`
per host. First idc03 tick baselines MDDB counters; cpu/log alerts can
fire immediately. See the trail doc's `deploy.next_step`.

## How to verify

- `python3 scripts/ops/retry-storm-watch.py --no-alert` on any
  container host — prints per-check verdict, exit 0.
- `python3 scripts/render-jobs.py --check` — manifest validates.
- Post-install: `systemctl --user list-timers retry-storm-watch.timer`
  on each host + `~/.local/state/retry-storm-watch.json` appears.

lessons:
- Dispatch worktrees can be far behind origin/master at session start;
  committing early and often matters — attempt 1's entire deliverable
  was lost because nothing was committed before the checkpoint failed.
- `podman stats --no-stream` CPU% is a lifetime-ish average, useless for
  a >50%-for-30min tripwire — stream it for a few seconds and keep the
  last row per container for a true interval measurement.
- `podman logs` writes container stderr to the process's stderr — merge
  stderr into stdout or you miss most WARN/ERROR lines.
- A failed MDDB fetch returning score 0 would fake a huge counter delta
  on recovery — return None on total fetch failure and keep the baseline.
- Plain-scalar YAML list items containing `: ` (e.g. "run on this host:")
  break safe_load — use `>-` folded scalars in trail docs.
