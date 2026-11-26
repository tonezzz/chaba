# dispatch-outcome — job-health-sweep-consecutive-failure-alerts

## What changed

- **`scripts/ops/job-health-sweep.py`** (new, ~720 lines): per-host sweep.
  Enumerates the host's `ssot.jobs.yml` `dispatch: systemd` jobs (same
  filter as render-jobs.py), probes `~/.config/systemd/user/<id>.{service,timer}`
  for missing units / disabled / inactive timers, then counts consecutive
  failed activations in `journalctl --user -u <id>.service` (window default
  "30 days ago"; short retention degrades to failed-since-boot). Flags at
  >=3 consecutive failures or >=1 attempt with zero successes. The
  newest->oldest streak walk dedupes the `Failed with result` /
  `Failed to start` marker pair per activation and extracts last_error
  from the newest failed activation's stdout. A drift pass flags installed
  `job:<id>`-tagged units not declared for the host (stale units surviving
  host moves). Journal/systemd probe failures surface once as a
  `sweep:probes` pseudo-verdict rather than false-flagging every job.
- **Alerting**: board-api only. One card `job-auto-health-<host>` (review /
  triage), comments on state change only — NEW failure per job (chunked
  <=500 chars when >6 at once), still-failing summary anchored ~20h into an
  episode, RECOVERED per job, `/action do=close` when fully green, reopen
  on relapse. State `~/.local/state/job-health-sweep.json` tracks
  per-key state/episode/first_seen; comment request_ids carry an episode
  counter so retries dedupe but same-day relapses still alert. Recovered
  state flips unconditionally so a stale "failing" flag can't suppress the
  next real alert.
- **`docs/ssot/infrastructure/ssot.jobs.yml`**: 5 entries (con01, idc02,
  idc03, mn01, tony_dell), `on_calendar: hourly`, `persistent: true`,
  `timeout: 10m`.
- **`systemd/generated/<host>/job-health-sweep.{service,timer}`** for all
  five hosts, plus re-render pickup of previously-missing
  `idc03/wp-comment-sync` (name drift) and `tony_dell/ansible-runner-tool-guard`
  units; removed 4 stale `con01/cline-*` units left by the fleet-wide Cline
  retirement (GeneratedTree was failing on them — pre-existing).
- **AUTO_RE** in `scripts/render-board.py`, `scripts/render-board2.py`,
  `scripts/test-board-dom.mjs`: added `job` to the auto-card prefix group so
  `job-auto-health-*` collapses under the automation group.
- **`tests/ops/test_job_health_sweep.py`**: 24 tests — streak dedupe,
  success-breaks-streak, orphan markers, last_error extraction, manifest
  filtering, timer probes, undeclared-unit drift, threshold gates, and the
  full board lifecycle incl. relapse re-alert.
- **Trail doc**: `docs/ssot/jobs/monitoring/2026-11-26-job-health-sweep.yml`.

## Result / verification

- Live run on idc02 (this host): **11 real findings** — 4
  declared-but-uninstalled jobs (`chaba-capture-harvest`,
  `job-health-sweep` itself pre-install, `opencode-models-sync`,
  `retry-storm-watch`) + 7 stale rendered units (`chaba-repo-mirror`,
  `devin-taskdir-prune`, `jev-bench`, `mddb-lab-pull`, `mddb-tier2-pull`,
  `session-audit`, `single-writer-fleet-audit`). Card
  **`job-auto-health-idc02` (OPS-1461, review, high)** created with 2
  chunked NEW-failure comments covering all 11 — the card-lands-on-idc03
  verification the spec asked for.
- Second live run: `comments new=0 summary=0 recovered=0`, comms count
  unchanged — anti-noise verified live.
- `embed-lane-banks` journal hand-checked: analyzer's consec=1/green
  matches reality.
- `pytest tests/ops`: 180 passed (incl. the 24 new + render_jobs
  GeneratedTree). Had to `pip install --user pillow` on idc02 first —
  pre-commit's fast gate was failing collection on missing PIL (env gap,
  not code).
- Committed `986ee521b5` on `dispatch/20261126-213829-context-three-con01-jobs-sat-d`.
  NOT pushed/deployed per dispatch rules. Post-merge install:
  `python3 scripts/render-jobs.py --host <h> --ids job-health-sweep --install`
  per host after chaba-repo-sync pulls the merge.

## How to verify

- `python3 -m pytest tests/ops/test_job_health_sweep.py -q`
- Board: `GET https://idc03.taila0626a.ts.net:10000/card/job-auto-health-idc02`
- Post-install per host: `systemctl --user list-timers job-health-sweep.timer`
  then `journalctl --user -u job-health-sweep.service -n 50`.

lessons:
- journalctl marker pairs: 'Failed with result' always sits just OLDER than 'Failed to start' — dedupe with a skip flag walking newest->oldest or you double-count every failed activation.
- unit stdout lands BETWEEN 'Starting' and 'Failed with result' chronologically — collect last_error candidates only after the newest 'Failed to start' marker in the backward walk.
- `systemctl --user is-system-running` exits nonzero on 'degraded' too — judge the state word, not the rc.
- board-api comment text is hard-capped at 500 chars — chunk flood-path comments and count keys per chunk, not lines per comment.
- idc02's user-site python lacked PIL, which broke the pre-commit pytest gate at collection for ANY scripts/ops commit — `pip install --user --break-system-packages pillow` fixed it (PEP 668 env).
