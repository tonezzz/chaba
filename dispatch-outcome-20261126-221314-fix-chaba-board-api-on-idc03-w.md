# Dispatch outcome — board-api-accept-loop-wedge-auto-restart-7dd2f1

## What changed

`scripts/board/board-api.py` (+292 lines): the 2026-11-26 idc03 wedge —
main thread parked in `Thread.start() -> _started.wait()` for ~20min,
every door 503/504 until manual restart — is now covered by two layers:

1. **Spawn isolation.** New `BoardAPIHTTPServer(ThreadingHTTPServer)`
   (used by `__main__`) overrides `process_request` to enqueue
   `(request, client_address)` onto a bounded queue
   (`BOARD_API_SPAWN_QUEUE_MAX=256`) drained by `BOARD_API_SPAWN_WORKERS=4`
   daemon workers that run the stock `socketserver.ThreadingMixIn.
   process_request` verbatim — so `Thread.start()`'s blocking
   `_started.wait()` can only park a worker, never `serve_forever`.
   Spawn exceptions close just that request; a saturated queue answers
   an inline 503 instead of letting clients hit the listen backlog.
2. **Liveness watchdog.** A daemon thread probes `GET /health`
   end-to-end on the server's own bound address every
   `BOARD_API_LIVENESS_INTERVAL_S=5`s (`TIMEOUT_S=6`,
   `FAILS=3`). Three consecutive failures = no door can be served
   (dead accept loop OR dead spawn path — serviceability, not one
   heartbeat) → `_on_liveness_wedge`: ACCEPT-LOOP-WATCHDOG journal line
   + `faulthandler` stack dump + one pending alert record +
   `os._exit(42)`. Nonzero exit trips the existing
   `Restart=on-failure`/`RestartSec=10` — worst-case recovery ~35-45s.
   `BOARD_API_LIVENESS_WATCHDOG=0` disables; `shutdown()`/`server_close()`
   stop the loop.
3. **One board/comms alert.** A wedged process can't post to itself, so
   the watchdog appends one JSON line to
   `~/.local/state/board-api-watchdog/alerts.jsonl`
   (`BOARD_API_WATCHDOG_DIR`). On next boot `_drain_watchdog_alerts()`
   posts ONE comms per record — req-stamped `watchdog-<epoch>-<pid>`,
   dedup-safe — to `BOARD_API_ALERT_CARD` (new card
   `board-api-watchdog-alerts`, column:done alert sink), falling back to
   a focus-inbox entry if the card doesn't resolve. Undelivered records
   persist for the next boot.

Supporting changes:
- `tests/board/test_board_api_liveness.py` (new, 5 tests): stuck
  `Thread.start()` parks one spawner while `/health` + `/cards` keep
  answering; spawn exceptions are non-fatal; all-spawns-blocked wedge
  fires recovery exactly once + writes one alert record; drain posts
  one deduped comms and falls back to focus-inbox.
- `scripts/board/dispatch_repos.py`: new test added to the chaba
  merge-gate smoke set; `runner-tooling.manifest.json` pin bumped in
  the same commit (tooling-contract gate).
- `docs/ssot/jobs/board/2026-11-26-board-api-accept-loop-watchdog.yml`:
  full trail incl. env knobs + deploy note.

## Result / verification

- `pytest tests/board/test_board_api_liveness.py` — **5 passed**
- `python3 scripts/board/board-api.py --selftest` — **selftest ok**
- Chaba merge-gate suite (`REPO_TESTS['chaba']`, now incl. the new
  file) — **305 passed in ~61s**
- Commit `94fb14ce516` on `dispatch/20261126-221314-fix-chaba-board-api-on-idc03-w`

## Deploy note

Merge → served checkout pull on idc03 lands the code (~15min cadence),
but systemd does not reload Python on file change — run once after the
pull lands:

```
ssh idc03 'systemctl --user restart chaba-board-api'
```

No unit change needed (`Restart=on-failure`/`RestartSec=10` already
matches exit-42). First real wedge produces one comms on
`board-api-watchdog-alerts` + ACCEPT-LOOP-WATCHDOG lines in
`journalctl --user -u chaba-board-api`. served-checkout-watchdog's
service-stale check will flag the mtime skew until the restart.
Rollback: revert the commit; stock `ThreadingHTTPServer` behavior
returns (the wedge risk returns with it).

lessons:
- Thread.start() blocking in _started.wait() parks the CALLER, not the
  new thread — any spawn done inline on a serve loop needs a worker
  pool; probe serviceability end-to-end (/health round-trip) rather than
  an internal heartbeat, it covers every wedge mode.
- A wedged service can't alert itself — write the alert record to disk
  and drain it post-restart, req-stamped for dedup.
- dispatch_repos.py is sha256-pinned in runner-tooling.manifest.json —
  ANY edit (even one line in REPO_TESTS) needs the pin bump in the same
  commit or test_runner_tooling_contract fails the gate.
- SSOT job YAML: multi-line plain-scalar mapping keys (path + parenthetical)
  break the syntax check — keep keys single-line, fold prose into >- values.
