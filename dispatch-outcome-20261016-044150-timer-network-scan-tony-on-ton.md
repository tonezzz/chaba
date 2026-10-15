# Dispatch outcome — timer network-scan-tony on tony-dell

Card: `timer-alert-tony-dell-network-scan-tony`
Branch: `dispatch/20261016-044150-timer-network-scan-tony-on-ton` (commit 991d8c2a1, not pushed)

## Finding

The 2026-10-14 19:43 failure was a **one-off boot race**, not an ongoing fault:

- tony-dell rebooted at 19:41:25. The timer (`OnBootSec=2m`) fired at 19:43:34
  while tony-ha was still coming up.
- `build-dossier-devices.py` got `ConnectionRefusedError` on `127.0.0.1:8123`
  (HA websocket) → exit 1 → `network-scan-tony.service` failed once.
- The next tick at 19:58 succeeded, and every 15-min run since is green
  (verified through Oct 16 04:29). Port 8123 is listening; exactly 1 failure
  since boot.

This is a **recurrence** of the `network-scan-startup-race` learning entry from
2026-09-21 — its prevention note ("wait for port 8123") was never implemented.

## Change (in this worktree, needs merge to reach chaba-tony-dell)

- `scripts/build-dossier-devices.py`: added `wait_for_ha()` — parses the
  websocket URL, polls the TCP endpoint for up to 180 s before connecting —
  called at the top of `build_and_push()` for every instance. A still-booting
  HA no longer fails the run; a genuinely down HA still fails after the
  timeout (alert stays meaningful).
- `docs/ssot/ssot.learning.post-restart-fixes.2026-09-21.yml`: recorded the
  2026-10-14 recurrence and the implemented fix in the entry's
  `fix`/`prevention` fields.

## Verification

- `python3 -m py_compile` clean; `wait_for_ha` functionally tested — returns
  immediately on a listening port, raises `TimeoutError` after the deadline on
  an unreachable one.
- Live state verified via ssh: `systemctl --user status network-scan-tony.service`
  → last run SUCCESS (04:29:34), timer active, next run 04:44.
- Note: the fix only takes effect on tony-dell once the dispatch branch merges
  and `chaba-tony-dell` pulls it. Until then the race can still recur on the
  next reboot (self-heals in ≤15 min as before).

## Suggested card action

Close as fixed-pending-merge: root cause found, code fix committed on the
dispatch branch; the alert itself is stale — the timer is healthy.
