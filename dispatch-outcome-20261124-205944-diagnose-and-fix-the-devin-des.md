# Dispatch outcome — fix-devin-desktop-startup-after-3-12-upgrade

## What was found

The "Devin Desktop starting error" on tony-dell and tony-omen was a
**split-brain single-instance** problem, not a package regression:

- `devin-desktop-watchdog.sh` runs from cron with a bare environment —
  no `XDG_RUNTIME_DIR`. Electron derives its single-instance socket
  location from that variable (`Qv=process.env.XDG_RUNTIME_DIR` in
  `resources/app/out/mainImpl.js`):
  - **set** → `/run/user/$UID/vscode-<hash>-<ver>-main.sock`
    (what interactive/desktop launches use)
  - **unset** → `~/.config/Devin/<ver>-main.sock` (what watchdog
    auto-restarts produced)
- The two socket families never see each other, so every launch after a
  watchdog relaunch spawned a **parallel instance** sharing the same
  `~/.config/Devin` profile — observed live as repeated LevelDB `LOCK`
  errors on `vscode-file_vscode-app_0.indexeddb.leveldb` and duplicate
  mains.
- tony-dell was worst hit: the watchdog-restarted pre-upgrade instance
  (PID 3271309, started Nov-23 16:10) kept running its **deleted**
  binary after the 19:13 upgrade to 3.14.30833, squatting on the
  user-data-dir socket while interactive launches spawned seconds.
- tony-omen had the same pattern (watchdog instance PID 47209 since
  Nov-23 19:00) though less visibly broken.

## What changed

- `scripts/devin/devin-desktop-watchdog.sh` — export
  `XDG_RUNTIME_DIR=/run/user/$(id -u)` when unset (guarded by dir
  existence) so watchdog-resurrected instances bind the same singleton
  socket as interactive launches. Syntax-checked, installed to
  `~/.local/bin/` on both hosts.
- Live remediation on both hosts: SIGTERM'd the stale mains (clean
  exit, zero leftover processes — sessions preserved, session DB
  untouched), relaunched on `DISPLAY=:20` with
  `XDG_RUNTIME_DIR=/run/user/1000` + `DBUS_SESSION_BUS_ADDRESS` via
  setsid (same method the watchdog uses).
- Trail doc: `docs/ssot/jobs/infrastructure/2026-11-24-devin-desktop-xdg-split-brain.yml`.

## Verified

- **tony-dell**: main PID 3426155, exe not deleted (3.14.30833), socket
  `/run/user/1000/vscode-5cc5eca6-1.14-main.sock`, `code.lock` matches,
  window "Host monitoring tab Untitled (Workspace) - Devin" viewable on
  `:20`, ACP agents respawned. Delegate test: second launch exited in
  ~1.1s, no second main survives.
- **tony-omen**: main PID 2925241, same socket path/lock, window
  "Please assess recent ada-ocb jobs ... tony-claude-code-00 (Workspace)
  - Devin" restored on `:20` — user sessions intact. Delegate test
  ~1.2s, single main remains.
- Fresh `main.log` sessions on both hosts show clean startup (only the
  usual benign datadog `vscode-file` noise).

## Notes / follow-ups

- Other hosts running this watchdog (installed via
  `scripts/devin/install-devin-host.sh`) should pick up the patched
  script on their next install run — cron env lacks `XDG_RUNTIME_DIR`
  everywhere.
- The recurring `renderer process gone (reason: killed, code: 61696)`
  events correlate with earlyoom pressure on the 16G hosts — separate
  issue, watchdog already notifies; not addressed here.
- No commits to master, no pushes, no reboots, no session-DB deletes.

lessons:
- Electron single-instance socket dir follows XDG_RUNTIME_DIR; headless launchers (cron/systemd --user without it) create split-brain instances invisible to desktop launches — always export XDG_RUNTIME_DIR when relaunching GUI apps from cron.
- `/proc/<pid>/exe -> ... (deleted)` after a package upgrade = stale pre-upgrade instance still running; it squats on profile locks and breaks single-instance delegation.
- Verify GUI app fixes by checking the actual singleton socket path (`/run/user/$UID/vscode-*-main.sock` vs `~/.config/<app>/<ver>-main.sock`), not just "a window exists".
- SIGTERM on the Electron main exits the whole tree cleanly (children + ACP agents die with it); relaunch restores workspace/session state from disk.
