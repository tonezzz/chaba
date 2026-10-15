# Dispatch outcome — timer-alert-tony-dell-tony-dell-mcp-health

## Result
`tony-dell-mcp-health.service` exit-code failure was a **post-reboot transient** on
2026-10-14 — already self-healed; no live fault. Card closed to done via board-api.

## What was found
- Only two failures in unit history: 19:44:25 and 19:49:25 +07 on 10-14, both inside
  tony-dell's rough boot (19:41) after an unclean shutdown. `chaba-postgres-16`
  (podman) needed 3 start attempts + WAL crash recovery; ready 19:50:17. Next timer
  run 19:54:26 succeeded; unit green every 5 min since (verified live 2026-10-16 04:41).
- SSH to tony-omen connected fine during the failures (auth.log: session opened) —
  the remote `mcp-health-client.py` exited non-zero in <1s. Exact error is
  unrecoverable: the script ran ssh with `2>/dev/null`.
- Side finding: **tony-omen gnome-keyring-daemon (pid 9755) pegged at 1024/1024 fds,
  ~30% CPU**, spamming auth.log "Too many open files" 100k+/day since 10-13 03:09,
  still active — carded as `tony-omen-gnome-keyring-daemon-fd-leak-p-338561` (SEC-0714).

## Changes (dispatch branch `dispatch/20261016-044213-…`, commit 791f3ea6)
- `scripts/tony-dell-mcp-health.sh`: synced repo copy to live semantics
  (`POSTGRES_HOST=100.68.142.13`, remote `chaba` path) and now logs ssh stderr to the
  journal on failure (`ssh-stderr:` lines) so the next flap is diagnosable.
- `docs/ssot/jobs/infrastructure/2026-10-16-tony-dell-mcp-health-postboot-flap.yml`:
  full investigation trail.

## Not done (needs live deploy, outside dispatch scope)
- Live `~/.local/bin/tony-dell-mcp-health.sh` on tony-dell still discards stderr —
  the canonical source is the `chaba-tony-dell` repo + manual deploy per
  `ssot.tony-dell-monitoring.yml`. Apply the same patch there.

## Verify
- `ssh tony-dell 'journalctl --user -u tony-dell-mcp-health.service -n 20'`
- `ssh tony-dell 'systemctl --user list-timers tony-dell-mcp-health.timer'`
- `ssh tony-dell 'cat ~/var/chaba/health/tony-dell-mcp-health.json'`
