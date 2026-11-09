# dispatch-outcome — timer-alert-idc03-kraut-rain-watch (2026-11-09)

## Verdict
Timer `kraut-rain-watch` on idc03 is **healthy**. The card was a stale
re-spawn, not a real recurrence — verified and closed to `done` via
board-api.

## What was found (evidence)
- `journalctl --user -u kraut-rain-watch.service` on idc03: the last real
  failure was **Nov 08 15:44:52** (`urllib.error.URLError: timed out`,
  status=1) — seconds before yesterday's relay fix landed at 15:45.
- Every 30-min run since 15:45 Nov 08 exits `status=0/SUCCESS` — ~44
  consecutive greens, including a live-observed 09:11 run today.
- TG sends confirmed working in journal (`{'ok': True, 'chat_id': 8960073266}`),
  latest real push Nov 09 00:11 (RAIN INCOMING).
- `michael-ha-via-omen-tunnel.service` (the fix's dependency): loaded,
  active, running.
- `~/.config/secrets/ada-ai-kraut.env` on idc03: present (created Nov 08 15:45).
- `kraut-rain-watch.timer`: active (waiting), next trigger normal.

## Why the card re-spawned
Card was closed 15:46 Nov 08, then re-queued 15:50 ("re-spawned from
report page"): `timer-sentinel.py` reads the 15-min timer-timeline sweep
state on tony-dell, which still carried `result=exit-code` from the 15:41
run. `_recent()` accepts failures <48h old, so one stale sweep re-fired
the just-closed card via `on_exists: queue`. Follow-up carded:
`timer-sentinel-stale-respawn` (OPS-1246) with fix options, recommending
a live `systemctl` re-check before re-queuing a recently-closed card.

## Actions taken
- Posted verification comment on `timer-alert-idc03-kraut-rain-watch`.
- Closed the card via `POST /action {do: close}` → column done.
- Created follow-up card `timer-sentinel-stale-respawn` (OPS-1246).
- No repo changes; no pushes; no host config changes.

## How to verify
```
ssh idc03 'systemctl --user status kraut-rain-watch.service --no-pager | head -8;
           journalctl --user -u kraut-rain-watch.service -n 20 --no-pager'
```
Expect `status=0/SUCCESS` and `rain-check ok:` lines every :11/:41.
