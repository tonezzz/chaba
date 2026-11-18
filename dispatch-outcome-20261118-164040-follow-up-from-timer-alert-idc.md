# Dispatch outcome — ada-memory-sync transient-MDDB hardening

Card: `ada-memory-sync-transient-mddb-hardening` (MEM-1253), follow-up from
`timer-alert-idc03-ada-memory-sync` (diagnosed 2026-11-09; ~8 self-healing
red alerts since 2026-11-08).
Branch: `dispatch/20261118-164040-follow-up-from-timer-alert-idc`, commit
`d88ead5812`. Not pushed (per dispatch rules).

## What changed

Implemented recommended options (1)+(3), plus the timeout bump retries
require:

1. **`scripts/ada/sync-ada-memory-to-mddb.py`** — `Mddb._post` now does
   bounded retry: 3 attempts, linear backoff 30s/60s, on transport faults
   (`requests.ConnectionError` incl. RemoteDisconnected/refused,
   `requests.Timeout`) and transient HTTP (429/5xx). Deterministic 4xx
   fails fast; a real outage still exits nonzero after exhaustion — real
   crashes stay red. All three callers are idempotent (`/search` read,
   `/add` upsert-by-key, `/delete` key-scoped). Retry attempts log to
   stderr (`mddb/add failed (...) — retrying in Ns`).
2. **Read timeout 20s → 60s** (deviation from the strict "recommend
   (1)+(3)", within spec option (2)): retries under a 20s cap cannot
   survive the documented ~30s/doc inline-embed stall that caused mode
   (b) — every attempt would ReadTimeout identically. 60s covers the
   observed worst case (~30-40s) with headroom. Flagging for review;
   easy to revert to 20 if unwanted.
3. **`systemd/ada-memory-sync.timer`** — `OnCalendar=hourly` →
   `*-*-* *:17:00`. Permanently off :00 so it can never collide with
   Sun-05:00 `mddb-restart.timer` (mode a). `:17` is unused across repo
   timers (`:30` ada-memory-pull, `:45` ada-memory-health, `:23`
   bench-edge-cms). Validated with `systemd-analyze calendar`.
4. **`systemd/ada-memory-sync.service`** — comment fix only: unit runs on
   idc03 (where the alerts fire) and mn01, not mn01-only.
5. **`tests/ada_memory/test_memory_scripts.py`** — new `TestMddbRetry`:
   transient→success (asserts 30s/60s sleeps), exhaustion re-raises,
   4xx fail-fast (no retry), 5xx retried. First test run caught a real
   bug (bare `raise` outside the except → RuntimeError); fixed.
6. **Trail doc** —
   `docs/ssot/jobs/infrastructure/2026-11-18-ada-memory-sync-mddb-transient-retry.yml`
   records the decision, deploy steps, and residuals.

Not done (spec option 4, rejected for now): exit-0 contract fold-in —
the unit also reports genuine unresolved conflicts via exit 1 and needs
a durable findings channel before conversion; remains the documented
residual in `docs/kb/timer-expectations.md`.

## Verification

- `python3 -m py_compile` clean.
- `python3 -m unittest tests.ada_memory.test_memory_scripts` — **26 tests
  OK** (new retry tests + all pre-existing).
- `systemd-analyze calendar '*-*-* *:17:00'` — valid, hourly at :17.
- New jobs yml passes yaml.safe_load + pre-commit SSOT validation.

## Deploy needed (not done in this session)

- Script propagates automatically via the `chaba-vault` job-checkout sync
  on idc03 + mn01 once merged.
- Units are **not** auto-installed: `scp systemd/ada-memory-sync.{timer,service}
  <host>:~/.config/systemd/user/ && ssh <host> 'systemctl --user
  daemon-reload && systemctl --user reenable ada-memory-sync.timer &&
  systemctl --user restart ada-memory-sync.timer'` for idc03 and mn01 —
  exact commands also in the trail doc.
- Verify after deploy: `systemctl --user list-timers ada-memory-sync.timer`
  shows NEXT ≈ :17; next run survives an mddb restart (journal shows
  "retrying in" lines instead of a crash).
