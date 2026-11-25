# Dispatch outcome — tony-omen snap desktop restart loop (attempt 3)

Card: `tony-omen-snap-desktop-restart-loop` (OPS-1323)
Date: 2026-11-25

## State carried in

Attempts 1-2 already found and fixed the root cause live on tony-omen:
the `snap.snapd-desktop-integration` user unit looped every ~12s with
`Failed to open display` because the CRD (Chrome Remote Desktop) Xvfb
session never exports DISPLAY/XAUTHORITY into `systemd --user`.
Fix = user drop-in
`~/.config/systemd/user/snap.snapd-desktop-integration.snapd-desktop-integration.service.d/override.conf`
with `Environment=DISPLAY=:20` + `XAUTHORITY=/home/tony/.Xauthority`.
This attempt re-verified it, closed the last verification gap with an
automated post-boot check, and landed the trail docs (attempt 1 left
them untracked; attempt 2 committed on its own branch).

## What attempt 3 verified (~22:10 +07)

- Fix healthy: `NRestarts=0` continuously from 09:54:57 to 15:05:28
  (~5h10m, zero display errors), drop-in confirmed in `DropInPaths`.
- **Burst-limit edge closed analytically + empirically**: measured a
  dead-display (`DISPLAY=:99`) `snap run` failing in ~12.5s. Each
  failed start therefore occupies ~14.5s of wall time (<1 start per
  10s `StartLimitInterval`), so `StartLimitBurst=5/10s` can never
  trip — the unit self-heals no matter how late Xvfb :20 appears
  post-boot. No drop-in change needed.
- **NRestarts=2 at 15:05-15:08 explained — not the bug**: the CRD
  display session itself was recreated (client tonezzzz@gmail.com
  connected 15:07:14, disconnected 15:07:57; chrome-remote-desktop
  child-process logged "Launching X server and X session" 15:08:01;
  new Xvfb :20 PID replaced the Nov-23 instance). The GTK daemon lost
  its X connection, exited status=2, and `Restart=on-failure`
  reconnected to the new display within ~60s. Occasional +1-2
  NRestarts on CRD session churn is correct behavior; the loop
  signature is repeated `Failed to open display` every ~12s.
- tony-omen still has NOT rebooted (up 1d20h+, load ~50, active CRD
  client session) — no unattended reboot performed or needed now.

## Post-boot verification — now automatic

The remaining done-condition ("restart count stops growing after
reboot") no longer needs a reboot window or Tony action. Armed on
tony-omen user crontab:

```
@reboot /home/tony/.local/bin/snap-boot-verify-ops1323.sh >> /home/tony/.local/state/snap-boot-verify-ops1323.log 2>&1
```

~5min after the next boot the script reads NRestarts / ActiveState /
display-error counts / Xvfb :20 presence, posts the verdict to this
card's comms via board-api, then removes its own cron line and
deletes itself. Guards: uptime>1200s skip (cron restarts mid-uptime
don't fire it), bus-readiness wait loop, state preserved in
`~/.local/state/snap-boot-verify-last.txt` even if the post fails.
Cancel early: `crontab -l | grep -v snap-boot-verify-ops1323 |
crontab - && rm ~/.local/bin/snap-boot-verify-ops1323.sh`.

## Deliverables in this worktree

- `docs/ssot/jobs/infrastructure/2026-11-25-tony-omen-snap-desktop-integration-display-fix.yml`
  — full trail: diagnosis, fix, attempt-2/3 verification, auto-verify
  design, rollback, gotchas.
- `dispatch-outcome-20261125-145936-find-why-snap-snapd-desktop-in.md`
  — this file.
- Live on tony-omen: systemd drop-in (attempt 1) + self-removing
  @reboot verifier (this attempt).

## Board state

- Request `snap-reboot-verify-window` (reboot-now / wait-natural /
  tony-reboots) left open — wait-natural is now the expected path
  since the verifier reports by itself; reboot-now still available if
  Tony wants instant confirmation.
- `$TASK_DIR/needs-input.txt` raised with the same choice.

lessons:
- Dead-display failure latency of `snap run` GTK apps is ~12.5s on tony-omen — compare against RestartSec+StartLimitBurst before assuming a boot-time race can park a unit failed.
- On CRD hosts the :20 X display is owned by a chrome-remote-desktop child-process and is recreated on client session churn — GTK user units restart once per recreation; judge loops by repeated "Failed to open display" journal lines, not NRestarts alone.
- User crontab @reboot fires on every cron-daemon start — gate one-shot post-boot jobs on /proc/uptime and only self-clean after a genuine fresh-boot run.
- A self-removing @reboot script + state file is the narrowest way to satisfy a "verify after reboot" done-condition when no reboot window exists.
