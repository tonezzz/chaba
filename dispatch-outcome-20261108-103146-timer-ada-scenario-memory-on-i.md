# Dispatch outcome — timer-alert-idc03-ada-scenario-memory (2026-11-08)

## Task
`ada-scenario-memory.service` on idc03 failed with `result=exit-code`
(last logged run 2026-11-04 05:55 +07, exit 1). Investigate journal.

## Findings

1. **The Nov 4 exit-1 was a stale finding-signal, not a crash.** The
   memory suite ran to completion (`**Score: 0.269`**, `auto-report: 9
   worthy item(s)` printed) but exited 1 under the pre-Nov-7 copy of
   `scenario-suite-run.sh`, which lacked the exit-1-with-report → 0
   mapping (OPS-0581 contract, `docs/kb/timer-expectations.md`).
2. **Fix was already deployed.** Live wrapper on idc03
   (`~/.local/share/ada-scenario-runner/scenario-suite-run.sh`, mtime
   Nov 7 17:50) is md5-identical to repo HEAD and contains both the
   Score-marker mapping and the paid-lane park guard.
3. **memory staying on :8002 is by design.** Commit 1c56115c5
   (bench-off-paid-lanes): memory/tools/casting stay prod-targeted but
   park by default; research/cms/reports move to dev lane :8005.
4. **Verified end-to-end:** `systemctl --user start
   ada-scenario-memory.service` → wrapper hit paid-lane guard →
   "parked, zero sessions opened" → exit 0, `Result=success`. Next
   timer run (Wed 2026-11-11 05:55) will be green.

## Changes made (host: idc03)

- `systemctl --user reset-failed` on the 5 stale scenario units:
  research, cms, memory, reports, tools (all failed Nov 2–6 under the
  old wrapper with the same finding-signal pattern).
- **Restarted `chaba-board-api.service`** — it was wedged: an outbound
  HTTPS send to rcloud03.siamdataidc.com:443 (WP host) hung with 4 KB
  unacked, serializing all write endpoints behind the flock. GETs/health
  worked; every POST timed out. Post-restart `/comment` and `/card`
  return 200. (Stuck handler was likely a `/lesson` remote-backed
  write — WP reachability to rcloud03 worth watching.)

## Left alone (real issues, already carded)

- `ada-embed-bench.service` — real crash, urllib HTTP 403 (Nov 7) →
  card `embed-bench-blocked-20261107` (backlog).
- `ada-scenario-smoke.service` — hourly timeouts (status=9/KILL) →
  card `ada-scenario-smoke-timeout-truncation`.
- Other unrelated failed job units on idc03 — out of scope.

## Follow-up carded

- `idc03-re-run-ada-scenario-runner-install-a77c3c` (ADA-1159, backlog):
  deployed `ada-scenario-*.service` unit files on idc03 are stale since
  Oct 23 — all still `ADA_LIVE_URL=:8002`, so research/cms/reports will
  park instead of running on dev lane until `install.sh` is re-run.

## Board

- Triage comment posted to `timer-alert-idc03-ada-scenario-memory`.

## How to verify

```
ssh idc03 'systemctl --user show ada-scenario-memory.service -p Result'
  # -> Result=success
ssh idc03 'systemctl --user list-units --state=failed --no-legend | grep scenario'
  # -> (no output; only ada-embed-bench remains, unrelated)
ssh idc03 'journalctl --user -u ada-scenario-memory.service -n 8 --no-pager'
  # -> Nov 08 run: "parked, zero sessions opened" + Finished
```
