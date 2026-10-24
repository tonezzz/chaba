# Dispatch outcome — restart gnome-keyring-daemon on tony-omen

Card: `tony-omen-gnome-keyring-daemon-fd-leak-p-338561`
Ran: 2026-10-24 ~19:51–19:54 +07 on tony-omen (in-place, user tony)

## What was found

- The card's target, `gnome-keyring-daemon[9755]`, was already dead. It had
  flooded `/var/log/auth.log` with `couldn't accept new control request:
  Too many open files` (~16–37K lines/hr, ~1M total) from at least Oct 18
  until Oct 19 ~16:59, then died when `user@1000.service` restarted at
  17:51 on Oct 19.
- The replacement daemon (pid 9340) had already been running clean for 5
  days: 12 fds, 0% CPU, no log spam. No clients were holding the
  control/pkcs11 sockets; the only desktop session is a
  chrome-remote-desktop session (c1).

## What was done

`systemctl --user restart gnome-keyring-daemon.service` at 19:52:56 — a
single-unit restart, no sessions touched.

## Verified (done-condition)

- Service active (running), new Main PID **1932432**, TriggeredBy socket ✓
- fd count **10** of 1024 limit ✓
- CPU **0.0%** sustained across samples and 46s elapsed ✓
- Zero `Too many open files` lines in auth.log post-restart; only routine
  sudo audit lines ✓
- `org.freedesktop.secrets` / `org.gnome.keyring` re-registered on user
  bus by the new pid ✓

## Trail & follow-ups

- Job trail written:
  `docs/ssot/jobs/infrastructure/2026-10-24-tony-omen-gnome-keyring-fd-leak.yml`
- Observed (not acted on): a transient `gnome-keyring-daemon` spawns daily
  at 18:51:41 without a session bus and exits — same headless-spawn
  pattern that likely produced the leaked instance; coincides with a daily
  SSH connect from tony-macbook. If the leak recurs, find that launcher.
- Unrelated noise noted on board: `snapd-desktop-integration` is
  crash-looping (~34,580 restarts, "Failed to open display").
- Board notified via `/comment` (investigation note + done note).

## How to re-verify

```bash
P=$(systemctl --user show -p MainPID --value gnome-keyring-daemon.service)
ls /proc/$P/fd | wc -l                 # ~10
ps -o %cpu,etime -p $P                 # ~0.0
sudo grep -c 'Too many open files' /var/log/auth.log   # static, no growth
```
