# logs-severe-hourly — hourly severe-line shipping lane

## What changed

- **`scripts/ada/log-shipper.py`** — new `--severe` flag (= `--kinds
  oom,panic,failed --cursor-tag severe`), plus generic `--kinds` and
  `--cursor-tag`. Tagged lanes get independent cursor files
  (`~/.cache/log-shipper-severe-{sys,user}.cursor`), an independent
  ha-cli dedup file (`log-shipper-ha-severe-<host>.json`), and post
  `ship-severe/<host>` state docs with `run=severe` — the severe lane can
  never advance the full lane's cursor past unshipped non-severe lines.
  `SEVERE_KINDS` mirrors `SEVERE` in logs-report.py (error deliberately
  excluded — catch-all bucket, too noisy).
- **`scripts/ada/logs-kanban.py`** — `ship_states()` only consumes
  `ship/` keys now, so side-lane heartbeats can't clobber full-lane
  counters (would have false-triggered backlog/one-sided cards).
- **`ssot.jobs.yml`** — 6× `log-shipper-severe` jobs (hourly `--self
  --severe` on tony_dell/tony_omen/idc01/idc02/idc03/mn01) +
  `log-shipper-severe-mha` on tony_dell (`--hosts michael-ha --severe`,
  the ha-cli pull twin).
- **`install-log-shipper.sh`** — bundles and arms the severe units;
  run-once exercises both lanes.
- **`systemd/generated/`** — rendered `log-shipper-severe.{service,timer}`
  per host + `log-shipper-severe-mha.*` on dell.
- **`docs/ssot/jobs/infrastructure/2026-10-06-log-shipper-severe-lane.yml`**
  — decision doc/runbook.

## Installed + verified live

- `log-shipper-severe.timer` armed on **dell, omen, idc01, idc02, idc03,
  mn01**; `log-shipper-severe-mha.timer` armed on dell. Verified via
  `systemctl --user list-timers` on every host.
- **Probe test passed**: injected
  `kernel: Out of memory: Killed process 4242 — severe-lane verify`
  into tony-omen's user journal at 10:55 +07 via `systemd-run --user`;
  it landed in MDDB host-logs as `hostlog/tony-omen/258916433008-9ca33cd9`
  (`kind=oom`) when `log-shipper-severe.service` ran at 11:02 — ~7 min,
  well within the hour.
- All 7 `ship-severe/<host>` state docs fresh with `run=severe`, err=-.

## Incident during rollout (not caused by this change)

MDDB leader (idc03 :11023) wedged 10:48–11:01 — a manually-started
`mddb-vector-reindex.service` blocked the HTTP API (health timeouts while
MCP sessions still cycled). Someone/something TERM'd the reindex at
11:00:31 and the API recovered instantly. Mid-wedge `/add` failures hit
the install run-once on idc01/02/03/mn01 — by design, cursors didn't
advance past unshipped lines; a manual re-run after recovery drained
them clean. Same wedge family as the (closed) `mddb-search-wedge` card —
vector-reindex still wedges the API while running; a parallel session
appears to be doing MDDB work today.

## Verify (operator)

- `systemctl --user list-timers 'log-shipper*'` on any host — two timers.
- `curl -X POST http://100.102.134.91:11023/v1/search -d
  '{"collection":"host-logs-state","query":"","limit":60}'` —
  `ship-severe/<host>` docs fresh hourly alongside `ship/<host>`.
- Doc `hostlog/tony-omen/258916433008-9ca33cd9` in host-logs is the
  injected probe.

## Caveats

- Severe lines get posted by both lanes eventually — same deterministic
  key, idempotent upsert (no duplicates).
- First severe run backfills up to 500 lines from the 7-day initial
  window; idc02 scanned 2722 severe/7d (~390/day of mostly 'failed' app
  noise) — drains over the next ticks, and may fire the kanban
  severe-spike card (>40/day) on noisy VPSes. That's legit signal.
- A truly dead host still can't ship anything — dead-host detection
  stays the stale-heartbeat signal (now on two keys).
